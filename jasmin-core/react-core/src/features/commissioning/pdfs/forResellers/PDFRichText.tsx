import { Text, View } from "@react-pdf/renderer";
import type { Style } from "@react-pdf/types";
import { Fragment, type ReactNode } from "react";

/**
 * Render Quill-saved HTML inside a react-pdf document while preserving
 * its blocks (paragraphs, headings, list items) and inline formatting.
 *
 * Parsing uses a regex tokenizer rather than ``DOMParser`` because the
 * PDF fixture tests run with ``@vitest-environment node`` where
 * ``DOMParser`` doesn't exist. Quill emits a small, well-formed subset
 * of HTML, so a hand-rolled tokenizer is enough and avoids a polyfill.
 *
 * Tags handled:
 *   - ``<p>``      → paragraph block
 *   - ``<h1>``–``<h3>`` → heading block, bold and larger
 *   - ``<ol>``/``<ul>`` + ``<li>`` → one block per item, prefixed "1." or "•"
 *   - ``<br>``     → soft line break (``"\n"`` inside the current text)
 *   - ``<strong>``/``<b>`` → ``fontWeight: "bold"``
 *   - ``<em>``/``<i>``     → ``fontStyle: "italic"``
 *   - ``<u>``      → underline
 *   - ``<s>``/``<strike>``/``<del>`` → line-through
 *   - ``<a>``      → underline (we don't generate real PDF links here,
 *     just visually mark them so a copy-out has the address)
 *
 * Lists come in two shapes. The editor saves Quill's semantic HTML —
 * ``<ol>`` for numbered and ``<ul>`` for bulleted items, a deeper level
 * as a list nested inside its parent ``<li>``. Quill's raw editor HTML
 * instead puts every item in one ``<ol>``, marks the kind on the item
 * (``<li data-list="bullet">``) and the depth as a ``ql-indent-N`` class.
 * Both are read here: ``data-list`` overrides the list tag, and the
 * indent class adds to the nesting depth.
 *
 * Unknown tags fall through transparently — their children render with
 * the inherited style. Colour isn't handled.
 */

type TextDecoration = "underline" | "line-through" | "underline line-through";

interface InlineStyle {
  fontWeight?: "bold";
  fontStyle?: "italic";
  textDecoration?: TextDecoration;
}

interface Run {
  text: string;
  style: InlineStyle;
}

type BlockKind =
  | { type: "paragraph" }
  | { type: "heading"; level: 1 | 2 | 3 }
  | { type: "listItem"; marker: string; depth: number };

interface Block {
  kind: BlockKind;
  runs: Run[];
}

type Token =
  | { type: "text"; value: string }
  | { type: "open"; tag: string; raw: string }
  | { type: "close"; tag: string }
  | { type: "void"; tag: string };

// Matches an opening tag, closing tag, or self-closing tag. ``[^>]*``
// permits attributes (``<a href="...">``) without trying to parse them.
const TAG_RE = /<\/?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(\/)?\s*>/g;
const VOID_TAGS = new Set(["br", "hr", "img"]);
const HEADING_LEVELS: Record<string, 1 | 2 | 3> = { h1: 1, h2: 2, h3: 3 };

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

// One pass, so a decoded ``&`` never starts another entity: ``&amp;lt;``
// prints as ``&lt;``.
const ENTITY_RE = /&(?:#(\d+)|#x([0-9a-fA-F]+)|([a-zA-Z]+));/g;

function decodeEntities(s: string): string {
  return s.replace(ENTITY_RE, (entity, decimal, hex, name) => {
    if (decimal || hex) {
      const codePoint = decimal
        ? Number.parseInt(decimal, 10)
        : Number.parseInt(hex, 16);
      if (codePoint === 0xa0) return " ";
      return codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : entity;
    }
    return NAMED_ENTITIES[name.toLowerCase()] ?? entity;
  });
}

/**
 * Insert zero-width spaces inside unbreakable long tokens (URLs, email
 * addresses, etc.) so react-pdf's text engine has somewhere to wrap.
 *
 * react-pdf measures a styled inline ``<Text>`` (like the underlined
 * run we emit for ``<a>``) as a single unbreakable unit. If that unit
 * is wider than the available line, the layout engine can't split it,
 * pushes the parent's width past the page area, and the surrounding
 * flex layout collapses to a narrow column. Inserting ``​``
 * (zero-width space, ``U+200B``) after each ``@`` / ``/`` / ``.`` /
 * ``-`` / ``_`` gives the engine breakable points without altering the
 * visible text — a copy-paste from the rendered PDF still produces the
 * original URL.
 *
 * Only applied to runs that look like a single token wider than ~30
 * characters with no whitespace — short link text ("here", "click")
 * doesn't need it and we don't want to over-process every run.
 */
function softenLongTokens(text: string): string {
  return text.replace(/\S{30,}/g, (token) =>
    token.replace(/([@/._\-])/g, "$1​"),
  );
}

function tokenize(html: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;
  // ``exec`` on a /g regex maintains its own ``lastIndex`` between
  // calls; reset it so successive ``tokenize`` invocations don't skip
  // matches from the previous run.
  TAG_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TAG_RE.exec(html)) !== null) {
    if (match.index > cursor) {
      tokens.push({ type: "text", value: html.slice(cursor, match.index) });
    }
    const raw = match[0];
    const tag = match[1].toLowerCase();
    const selfClosing = !!match[2] || VOID_TAGS.has(tag);
    if (selfClosing) {
      tokens.push({ type: "void", tag });
    } else if (raw.startsWith("</")) {
      tokens.push({ type: "close", tag });
    } else {
      tokens.push({ type: "open", tag, raw });
    }
    cursor = TAG_RE.lastIndex;
  }
  if (cursor < html.length) {
    tokens.push({ type: "text", value: html.slice(cursor) });
  }
  return tokens;
}

function addDecoration(
  current: TextDecoration | undefined,
  added: "underline" | "line-through",
): TextDecoration {
  if (!current || current === added) return added;
  return "underline line-through";
}

function applyTagStyle(tag: string, base: InlineStyle): InlineStyle {
  const next: InlineStyle = { ...base };
  if (tag === "strong" || tag === "b") next.fontWeight = "bold";
  else if (tag === "em" || tag === "i") next.fontStyle = "italic";
  else if (tag === "u" || tag === "a") {
    next.textDecoration = addDecoration(base.textDecoration, "underline");
  } else if (tag === "s" || tag === "strike" || tag === "del") {
    next.textDecoration = addDecoration(base.textDecoration, "line-through");
  }
  return next;
}

/** Whether a list item is numbered: its own ``data-list`` wins over the
 *  list's tag. Checklist items (``checked`` / ``unchecked``) print as
 *  bullets. */
function isOrderedItem(raw: string, listIsOrdered: boolean): boolean {
  const dataList = /\bdata-list\s*=\s*["']?([a-z]+)/i.exec(raw)?.[1];
  if (!dataList) return listIsOrdered;
  return dataList.toLowerCase() === "ordered";
}

function indentOf(raw: string): number {
  const indent = /\bql-indent-(\d+)\b/.exec(raw)?.[1];
  return indent ? Number.parseInt(indent, 10) : 0;
}

class HtmlBlockParser {
  readonly blocks: Block[] = [];
  private runs: Run[] = [];
  private kind: BlockKind = { type: "paragraph" };
  // Stack of inline styles. The bottom entry is the empty baseline; we
  // push on inline opens and pop on closes. Block tags don't push.
  private readonly styleStack: InlineStyle[] = [{}];
  // One entry per open list: whether its tag numbers its items.
  private readonly lists: boolean[] = [];
  // Item counter per nesting depth; deeper counters restart whenever a
  // shallower item appears.
  private counters: number[] = [];

  private topStyle(): InlineStyle {
    return this.styleStack[this.styleStack.length - 1];
  }

  private flush(nextKind: BlockKind = { type: "paragraph" }) {
    if (this.runs.length > 0) {
      this.blocks.push({ kind: this.kind, runs: this.runs });
      this.runs = [];
    }
    this.kind = nextKind;
  }

  text(value: string) {
    const decoded = softenLongTokens(decodeEntities(value));
    if (decoded) this.runs.push({ text: decoded, style: this.topStyle() });
  }

  void(tag: string) {
    // Other void tags (``<hr>``, ``<img>``) silently drop.
    if (tag === "br") this.runs.push({ text: "\n", style: this.topStyle() });
  }

  open(tag: string, raw: string) {
    if (tag === "p") return;
    const headingLevel = HEADING_LEVELS[tag];
    if (headingLevel) {
      this.flush({ type: "heading", level: headingLevel });
    } else if (tag === "ol" || tag === "ul") {
      this.flush();
      this.lists.push(tag === "ol");
      this.counters.length = this.lists.length - 1;
    } else if (tag === "li") {
      this.openListItem(raw);
    } else {
      this.styleStack.push(applyTagStyle(tag, this.topStyle()));
    }
  }

  private openListItem(raw: string) {
    const listIsOrdered = this.lists[this.lists.length - 1] ?? false;
    const depth = Math.max(this.lists.length - 1, 0) + indentOf(raw);
    this.counters.length = depth + 1;
    let marker = "•";
    if (isOrderedItem(raw, listIsOrdered)) {
      this.counters[depth] = (this.counters[depth] ?? 0) + 1;
      marker = `${this.counters[depth]}.`;
    }
    this.flush({ type: "listItem", marker, depth });
  }

  close(tag: string) {
    if (tag === "p" || tag === "li" || HEADING_LEVELS[tag]) {
      this.flush();
    } else if (tag === "ol" || tag === "ul") {
      this.flush();
      this.lists.pop();
      if (this.lists.length === 0) this.counters = [];
    } else if (this.styleStack.length > 1) {
      // Pop the matching style frame. We don't validate that the
      // closing tag matches the open — Quill output is well-formed, so a
      // mismatched ``</strong>`` against an open ``<em>`` would already
      // be broken at the source.
      this.styleStack.pop();
    }
  }

  /** Trailing inline content outside any block becomes one more block. */
  finish(): Block[] {
    this.flush();
    return this.blocks;
  }
}

function parseHtml(html: string): Block[] {
  const parser = new HtmlBlockParser();
  for (const tok of tokenize(html)) {
    if (tok.type === "text") parser.text(tok.value);
    else if (tok.type === "void") parser.void(tok.tag);
    else if (tok.type === "open") parser.open(tok.tag, tok.raw);
    else parser.close(tok.tag);
  }
  return parser.finish();
}

function styleIsEmpty(style: InlineStyle): boolean {
  return (
    !style.fontWeight && !style.fontStyle && !style.textDecoration
  );
}

const HEADING_STYLES: Record<1 | 2 | 3, Style> = {
  1: { fontSize: 14, fontWeight: "bold", marginBottom: 3 },
  2: { fontSize: 12, fontWeight: "bold", marginBottom: 2 },
  3: { fontSize: 11, fontWeight: "bold", marginBottom: 2 },
};

const LIST_INDENT_PER_LEVEL = 12;

const blockStyle: Style = {
  width: "100%",
  alignSelf: "stretch",
  flexShrink: 0,
};

function withStyle(base: Style | undefined, extra: Style): Style | Style[] {
  return base ? [base, extra] : extra;
}

function Runs({ runs }: { runs: Run[] }) {
  return (
    <>
      {runs.map((run, runIdx): ReactNode => {
        if (styleIsEmpty(run.style)) {
          return <Fragment key={runIdx}>{run.text}</Fragment>;
        }
        return (
          <Text key={runIdx} style={run.style as Style}>
            {run.text}
          </Text>
        );
      })}
    </>
  );
}

function BlockView({ block, style }: { block: Block; style?: Style }) {
  const { kind } = block;
  if (kind.type === "listItem") {
    // Marker and text sit side by side, so a wrapped item's second line
    // lines up with its text rather than under the marker.
    return (
      <View
        style={[
          blockStyle,
          {
            flexDirection: "row",
            paddingLeft: kind.depth * LIST_INDENT_PER_LEVEL,
          },
        ]}
      >
        <Text style={withStyle(style, { width: 14, flexShrink: 0 })}>
          {`${kind.marker} `}
        </Text>
        <Text style={withStyle(style, { flexGrow: 1, flexShrink: 1 })}>
          <Runs runs={block.runs} />
        </Text>
      </View>
    );
  }
  const textStyle =
    kind.type === "heading" ? withStyle(style, HEADING_STYLES[kind.level]) : style;
  return (
    <View style={blockStyle}>
      <Text style={textStyle}>
        <Runs runs={block.runs} />
      </Text>
    </View>
  );
}

export interface PDFRichTextProps {
  /** Quill-saved HTML. ``null``/``undefined``/``""`` renders nothing. */
  html?: string | null;
  /** Optional baseline style applied to every paragraph wrapper. */
  style?: Style;
}

export default function PDFRichText({ html, style }: PDFRichTextProps) {
  if (!html) return null;
  const blocks = parseHtml(html);
  if (blocks.length === 0) return null;

  // Layout shape:
  //
  //   <View outerWrapper>             ← single, definite, stretched
  //     <View block 1>                ← per-block (paragraph, heading, item)
  //       <Text>…runs…</Text>
  //     </View>
  //     <View block 2>
  //       …
  //     </View>
  //   </View>
  //
  // Why an OUTER wrapper instead of returning a ``Fragment`` of
  // block Views directly: a Fragment makes its children become
  // direct siblings of the caller's container. When ``PDFRichText`` is
  // used inside ``PDFEntryLines``' ``<View styles.entrySection>`` and
  // emits *multiple* Views (e.g. the two-paragraph
  // ``order_instructions`` field), react-pdf's reconciler tends to
  // collapse those sibling Views to their intrinsic content width
  // instead of stretching them — visually the text wraps inside a
  // narrow left "column". Anchoring the whole rich-text output in one
  // explicitly stretched outer View prevents that collapse: the
  // engine measures ONE box, stretches it, and the per-block
  // children inside inherit the full available width.
  return (
    <View style={blockStyle}>
      {blocks.map((block, blockIdx) => (
        <BlockView key={blockIdx} block={block} style={style} />
      ))}
    </View>
  );
}
