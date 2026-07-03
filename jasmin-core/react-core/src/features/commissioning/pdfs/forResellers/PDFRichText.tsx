import { Text, View } from "@react-pdf/renderer";
import type { Style } from "@react-pdf/types";
import { Fragment, type ReactNode } from "react";

/**
 * Render Quill-saved HTML inside a react-pdf document while preserving
 * inline formatting (``<strong>`` / ``<b>``, ``<em>`` / ``<i>``,
 * ``<u>``), paragraph breaks (``<p>``) and soft breaks (``<br>``).
 *
 * Replacement for the regex-based ``stripHtmlToText`` in
 * ``src/utils/pdfUtils.jsx``, which threw away ALL inline styling and
 * collapsed every paragraph into one big run of text.
 *
 * Parsing uses a regex tokenizer rather than ``DOMParser`` because the
 * PDF fixture tests run with ``@vitest-environment node`` where
 * ``DOMParser`` doesn't exist. Quill emits a small, well-formed subset
 * of HTML (paragraphs, line breaks, three inline marks, optional links)
 * so a hand-rolled tokenizer is enough and avoids a polyfill.
 *
 * Tags handled:
 *   - ``<p>``      → paragraph block
 *   - ``<br>``     → soft line break (``"\n"`` inside the current text)
 *   - ``<strong>``/``<b>`` → ``fontWeight: "bold"``
 *   - ``<em>``/``<i>``     → ``fontStyle: "italic"``
 *   - ``<u>``      → ``textDecoration: "underline"``
 *   - ``<a>``      → underline (we don't generate real PDF links here,
 *     just visually mark them so a copy-out has the address)
 *
 * Unknown tags fall through transparently — their children render with
 * the inherited style. Bullet lists / headings / colour aren't handled
 * yet; the reseller-doc UI's RTE has them in its toolbar so they may
 * appear over time. Extend ``applyTagStyle`` below when they do.
 */

interface InlineStyle {
  fontWeight?: "bold";
  fontStyle?: "italic";
  textDecoration?: "underline";
}

interface Run {
  text: string;
  style: InlineStyle;
}

interface Paragraph {
  runs: Run[];
}

type Token =
  | { type: "text"; value: string }
  | { type: "open"; tag: string }
  | { type: "close"; tag: string }
  | { type: "void"; tag: string };

// Matches an opening tag, closing tag, or self-closing tag. ``[^>]*``
// permits attributes (``<a href="...">``) without trying to parse them.
const TAG_RE = /<\/?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(\/)?\s*>/g;
const VOID_TAGS = new Set(["br", "hr", "img"]);

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#039;/g, "'")
    .replace(/&nbsp;/g, " ");
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
  const TRIGGER_LEN = 30;
  return text.replace(/\S{30,}/g, (token) => {
    if (token.length < TRIGGER_LEN) return token;
    return token.replace(/([@/._\-])/g, "$1​");
  });
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
      tokens.push({ type: "open", tag });
    }
    cursor = TAG_RE.lastIndex;
  }
  if (cursor < html.length) {
    tokens.push({ type: "text", value: html.slice(cursor) });
  }
  return tokens;
}

function applyTagStyle(tag: string, base: InlineStyle): InlineStyle {
  const next: InlineStyle = { ...base };
  if (tag === "strong" || tag === "b") next.fontWeight = "bold";
  else if (tag === "em" || tag === "i") next.fontStyle = "italic";
  else if (tag === "u" || tag === "a") next.textDecoration = "underline";
  return next;
}

function parseHtml(html: string): Paragraph[] {
  const tokens = tokenize(html);
  const paragraphs: Paragraph[] = [];
  let currentRuns: Run[] = [];
  // Stack of inline styles. The bottom entry is the empty baseline; we
  // push on inline opens and pop on closes. ``<p>`` is a block, not a
  // style change, so it doesn't push.
  const styleStack: InlineStyle[] = [{}];

  function topStyle(): InlineStyle {
    return styleStack[styleStack.length - 1];
  }

  function flushParagraph() {
    if (currentRuns.length > 0) {
      paragraphs.push({ runs: currentRuns });
      currentRuns = [];
    }
  }

  for (const tok of tokens) {
    if (tok.type === "text") {
      const decoded = softenLongTokens(decodeEntities(tok.value));
      if (decoded) currentRuns.push({ text: decoded, style: topStyle() });
      continue;
    }
    if (tok.type === "void") {
      if (tok.tag === "br") {
        currentRuns.push({ text: "\n", style: topStyle() });
      }
      // Other void tags (``<hr>``, ``<img>``) silently drop — see
      // module docstring about extending tag coverage when needed.
      continue;
    }
    if (tok.type === "open") {
      if (tok.tag === "p") {
        // Paragraph block: doesn't change style. Children render at
        // the current style; ``</p>`` is what commits the runs.
        continue;
      }
      styleStack.push(applyTagStyle(tok.tag, topStyle()));
      continue;
    }
    // tok.type === "close"
    if (tok.tag === "p") {
      flushParagraph();
      continue;
    }
    // Pop the matching style frame. We don't validate that the
    // closing tag matches the open — Quill output is well-formed, so a
    // mismatched ``</strong>`` against an open ``<em>`` would already
    // be broken at the source.
    if (styleStack.length > 1) styleStack.pop();
  }

  // Trailing inline content not wrapped in a <p> gets emitted as one
  // more paragraph.
  flushParagraph();

  return paragraphs;
}

function styleIsEmpty(style: InlineStyle): boolean {
  return (
    !style.fontWeight && !style.fontStyle && !style.textDecoration
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
  const paragraphs = parseHtml(html);
  if (paragraphs.length === 0) return null;

  // Layout shape:
  //
  //   <View outerWrapper>             ← single, definite, stretched
  //     <View paragraph 1>            ← per-paragraph block
  //       <Text>…runs…</Text>
  //     </View>
  //     <View paragraph 2>
  //       …
  //     </View>
  //   </View>
  //
  // Why an OUTER wrapper instead of returning a ``Fragment`` of
  // paragraph Views directly: a Fragment makes its children become
  // direct siblings of the caller's container. When ``PDFRichText`` is
  // used inside ``PDFEntryLines``' ``<View styles.entrySection>`` and
  // emits *multiple* Views (e.g. the two-paragraph
  // ``order_instructions`` field), react-pdf's reconciler tends to
  // collapse those sibling Views to their intrinsic content width
  // instead of stretching them — visually the text wraps inside a
  // narrow left "column". Anchoring the whole rich-text output in one
  // explicitly stretched outer View prevents that collapse: the
  // engine measures ONE box, stretches it, and the per-paragraph
  // children inside inherit the full available width.
  return (
    <View
      style={{
        width: "100%",
        alignSelf: "stretch",
        flexShrink: 0,
      }}
    >
      {paragraphs.map((paragraph, paragraphIdx) => (
        <View
          key={paragraphIdx}
          style={{
            width: "100%",
            alignSelf: "stretch",
            flexShrink: 0,
          }}
        >
          <Text style={style}>
            {paragraph.runs.map((run, runIdx): ReactNode => {
              if (styleIsEmpty(run.style)) {
                return (
                  <Fragment key={runIdx}>{run.text}</Fragment>
                );
              }
              return (
                <Text key={runIdx} style={run.style as Style}>
                  {run.text}
                </Text>
              );
            })}
          </Text>
        </View>
      ))}
    </View>
  );
}
