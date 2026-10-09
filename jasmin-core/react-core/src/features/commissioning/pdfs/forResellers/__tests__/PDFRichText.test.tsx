/**
 * PDFRichText: prints the HTML the reseller-document text editor saves
 * (paragraphs, line breaks, bold / italic / underline, links) into a PDF.
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const { pdfDomPrimitives } = await import(
    "@features/commissioning/pdfs/__tests__/pdfDomPrimitives"
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    ...pdfDomPrimitives(),
  };
});

import { styleOf } from "../../__tests__/pdfDomPrimitives";
import PDFRichText from "../PDFRichText";

const ZWSP = "​";

/** The printed paragraphs: one text per paragraph block. */
function paragraphs(html: string | null | undefined) {
  const { container } = render(<PDFRichText html={html} />);
  const outer = container.firstElementChild;
  if (!outer) return [];
  return Array.from(outer.children).map(
    (paragraph) => paragraph.textContent ?? "",
  );
}

/** The styled runs: each nested Text inside a paragraph, with its style. */
function styledRuns(html: string) {
  const { container } = render(<PDFRichText html={html} />);
  return Array.from(
    container.querySelectorAll("[data-pdf='text'] [data-pdf='text']"),
  ).map((run) => ({ text: run.textContent, style: styleOf(run) }));
}

describe("PDFRichText — empty input", () => {
  it.each([null, undefined, ""])("prints nothing for %j", (html) => {
    const { container } = render(<PDFRichText html={html} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("prints nothing for an empty paragraph", () => {
    const { container } = render(<PDFRichText html="<p></p>" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("PDFRichText — blocks", () => {
  it("prints plain text as one paragraph", () => {
    expect(paragraphs("Thank you for your order.")).toEqual([
      "Thank you for your order.",
    ]);
  });

  it("prints each paragraph as its own block", () => {
    expect(paragraphs("<p>Dear customer,</p><p>here is your note.</p>")).toEqual(
      ["Dear customer,", "here is your note."],
    );
  });

  it("keeps trailing text outside a paragraph as one more paragraph", () => {
    expect(paragraphs("<p>First</p>Second")).toEqual(["First", "Second"]);
  });

  it("turns a line break into a newline inside the paragraph", () => {
    expect(paragraphs("<p>Line one<br>Line two<br/>Line three</p>")).toEqual([
      "Line one\nLine two\nLine three",
    ]);
  });

  it("keeps an editor blank line as an empty line", () => {
    expect(paragraphs("<p>Above</p><p><br></p><p>Below</p>")).toEqual([
      "Above",
      "\n",
      "Below",
    ]);
  });

  it("lets every paragraph stretch to the full width", () => {
    const { container } = render(<PDFRichText html="<p>a</p><p>b</p>" />);
    const outer = container.firstElementChild!;
    expect(styleOf(outer)).toMatchObject({ width: "100%", alignSelf: "stretch" });
    for (const paragraph of Array.from(outer.children)) {
      expect(styleOf(paragraph)).toMatchObject({ width: "100%" });
    }
  });

  it("applies the baseline style to every paragraph's text", () => {
    const { container } = render(
      <PDFRichText html="<p>a</p><p>b</p>" style={{ fontSize: 8 }} />,
    );
    const texts = container.querySelectorAll(
      "[data-pdf='view'] > [data-pdf='view'] > [data-pdf='text']",
    );
    expect(texts).toHaveLength(2);
    texts.forEach((text) => expect(styleOf(text)).toEqual({ fontSize: 8 }));
  });

  // The editor's toolbar offers lists and headings; their items have to stay
  // apart rather than run together into one line.
  it("prints list items and headings as separate lines", () => {
    expect(
      paragraphs(
        "<h2>Opening hours</h2><ol><li>Monday</li><li>Thursday</li></ol>",
      ),
    ).toEqual(["Opening hours", "1. Monday", "2. Thursday"]);
  });
});

describe("PDFRichText — headings", () => {
  it.each([
    ["h1", 14],
    ["h2", 12],
    ["h3", 11],
  ])("prints <%s> bold at %ipt on a line of its own", (tag, fontSize) => {
    const { container } = render(
      <PDFRichText html={`<p>before</p><${tag}>Title</${tag}>after`} />,
    );
    const blocks = Array.from(container.firstElementChild!.children);
    expect(blocks.map((block) => block.textContent)).toEqual([
      "before",
      "Title",
      "after",
    ]);
    expect(styleOf(blocks[1].firstElementChild!)).toMatchObject({
      fontSize,
      fontWeight: "bold",
    });
    expect(styleOf(blocks[2].firstElementChild!)).toEqual({});
  });

  it("lays the heading style over the baseline style", () => {
    const { container } = render(
      <PDFRichText html="<h1>Title</h1>" style={{ color: "#333" }} />,
    );
    const text = container.querySelector("[data-pdf='text']")!;
    expect(styleOf(text)).toMatchObject({ color: "#333", fontSize: 14 });
  });

  it("keeps inline marks inside a heading", () => {
    expect(styledRuns("<h2>Big <em>news</em></h2>")).toEqual([
      { text: "news", style: { fontStyle: "italic" } },
    ]);
  });
});

describe("PDFRichText — lists", () => {
  /** Each list item's marker and text, with its indent. */
  function listItems(html: string) {
    const { container } = render(<PDFRichText html={html} />);
    return Array.from(container.firstElementChild!.children).map((item) => {
      const [marker, body] = Array.from(item.children);
      return {
        marker: marker.textContent,
        text: body.textContent,
        indent: styleOf(item).paddingLeft,
      };
    });
  }

  it("bullets the items of an unordered list", () => {
    expect(listItems("<ul><li>Carrots</li><li>Leeks</li></ul>")).toEqual([
      { marker: "• ", text: "Carrots", indent: 0 },
      { marker: "• ", text: "Leeks", indent: 0 },
    ]);
  });

  it("numbers each list from one", () => {
    expect(
      paragraphs("<ol><li>a</li><li>b</li></ol><p>x</p><ol><li>c</li></ol>"),
    ).toEqual(["1. a", "2. b", "x", "1. c"]);
  });

  it("indents and renumbers a list nested in an item", () => {
    expect(
      listItems(
        "<ol><li>Order<ol><li>by Monday</li><li>by noon</li></ol></li><li>Collect</li></ol>",
      ),
    ).toEqual([
      { marker: "1. ", text: "Order", indent: 0 },
      { marker: "1. ", text: "by Monday", indent: 12 },
      { marker: "2. ", text: "by noon", indent: 12 },
      { marker: "2. ", text: "Collect", indent: 0 },
    ]);
  });

  it("reads Quill's raw item kinds and indent classes", () => {
    expect(
      listItems(
        '<ol><li data-list="ordered"><span class="ql-ui" contenteditable="false"></span>One</li>' +
          '<li data-list="bullet" class="ql-indent-1">Sub</li>' +
          '<li data-list="ordered">Two</li><li data-list="checked">Done</li></ol>',
      ),
    ).toEqual([
      { marker: "1. ", text: "One", indent: 0 },
      { marker: "• ", text: "Sub", indent: 12 },
      { marker: "2. ", text: "Two", indent: 0 },
      { marker: "• ", text: "Done", indent: 0 },
    ]);
  });

  it("keeps inline marks inside an item", () => {
    expect(styledRuns("<ul><li><strong>Fresh</strong> eggs</li></ul>")).toEqual([
      { text: "Fresh", style: { fontWeight: "bold" } },
    ]);
  });

  it("drops an empty item", () => {
    expect(paragraphs("<ul><li></li><li>a</li></ul>")).toEqual(["• a"]);
  });
});

describe("PDFRichText — inline marks", () => {
  it.each([
    ["strong", { fontWeight: "bold" }],
    ["b", { fontWeight: "bold" }],
    ["em", { fontStyle: "italic" }],
    ["i", { fontStyle: "italic" }],
    ["u", { textDecoration: "underline" }],
  ])("styles <%s>", (tag, style) => {
    expect(styledRuns(`<p>plain <${tag}>marked</${tag}> plain</p>`)).toEqual([
      { text: "marked", style },
    ]);
    expect(paragraphs(`<p>plain <${tag}>marked</${tag}> plain</p>`)).toEqual([
      "plain marked plain",
    ]);
  });

  // The editor offers strikethrough; struck-out text must not print as if it
  // were still valid.
  it("strikes through <s>", () => {
    expect(styledRuns("<p>was <s>12 €</s> now 10 €</p>")).toEqual([
      { text: "12 €", style: { textDecoration: "line-through" } },
    ]);
  });

  it.each(["strike", "del"])("strikes through <%s>", (tag) => {
    expect(styledRuns(`<p><${tag}>gone</${tag}></p>`)).toEqual([
      { text: "gone", style: { textDecoration: "line-through" } },
    ]);
  });

  it("both underlines and strikes through nested marks", () => {
    expect(styledRuns("<p><u>a<s>b</s></u></p>")).toEqual([
      { text: "a", style: { textDecoration: "underline" } },
      { text: "b", style: { textDecoration: "underline line-through" } },
    ]);
  });

  it("underlines a link and prints its text, not its address attribute", () => {
    expect(
      styledRuns('<p>See <a href="https://farm.test" target="_blank">our site</a></p>'),
    ).toEqual([{ text: "our site", style: { textDecoration: "underline" } }]);
    expect(
      paragraphs('<p>See <a href="https://farm.test">our site</a></p>'),
    ).toEqual(["See our site"]);
  });

  it("combines nested marks and drops them again after closing", () => {
    expect(
      styledRuns("<p><strong>bold <em>both</em> bold</strong> plain</p>"),
    ).toEqual([
      { text: "bold ", style: { fontWeight: "bold" } },
      { text: "both", style: { fontWeight: "bold", fontStyle: "italic" } },
      { text: " bold", style: { fontWeight: "bold" } },
    ]);
  });

  it("reads tags in any case", () => {
    expect(styledRuns("<P><STRONG>Loud</STRONG></P>")).toEqual([
      { text: "Loud", style: { fontWeight: "bold" } },
    ]);
  });

  it("prints the text of unknown tags with the surrounding style", () => {
    expect(
      paragraphs('<p><span class="ql-size-large">Big</span> news</p>'),
    ).toEqual(["Big news"]);
    expect(styledRuns('<p><span class="x">Big</span></p>')).toEqual([]);
  });

  it("ignores a closing tag that was never opened", () => {
    expect(paragraphs("<p>a</em>b</strong>c</p>")).toEqual(["abc"]);
    expect(styledRuns("<p>a</em>b</p>")).toEqual([]);
  });

  it("drops images and rules", () => {
    expect(paragraphs('<p>a<img src="x.png"/>b<hr>c</p>')).toEqual(["abc"]);
  });
});

describe("PDFRichText — text content", () => {
  it("decodes the entities the editor writes", () => {
    expect(
      paragraphs("<p>Fish &amp; chips &lt;3 &gt; &quot;x&quot; it&#39;s it&#039;s a&nbsp;b</p>"),
    ).toEqual(['Fish & chips <3 > "x" it\'s it\'s a b']);
  });

  // An escaped ampersand must decode once: typing "&lt;" in the editor saves
  // "&amp;lt;", which has to print as "&lt;", not as "<".
  it("decodes an escaped entity only once", () => {
    expect(paragraphs("<p>Write &amp;lt;b&amp;gt; or &amp;nbsp;</p>")).toEqual([
      "Write &lt;b&gt; or &nbsp;",
    ]);
  });

  it("decodes numeric entities and leaves unknown ones as written", () => {
    expect(paragraphs("<p>&#8364; &#x20AC; &#160;x &bogus; &#xFFFFFFF;</p>")).toEqual([
      "€ €  x &bogus; &#xFFFFFFF;",
    ]);
  });

  it("prints a literal less-than sign that starts no tag", () => {
    expect(paragraphs("<p>1 < 2 and 3 <4</p>")).toEqual(["1 < 2 and 3 <4"]);
  });

  it("never prints markup, even of a script tag", () => {
    const [printed] = paragraphs(
      '<p>Hi<script type="text/javascript">alert(1)</script><style>p{}</style></p>',
    );
    expect(printed).not.toMatch(/<|>/);
    expect(printed.startsWith("Hi")).toBe(true);
  });

  it("gives a long unbroken address places to wrap without changing what it says", () => {
    const url = "https://www.example-farm.test/orders/reseller_documents";
    const [printed] = paragraphs(`<p>Order at ${url} today</p>`);
    expect(printed).toContain(ZWSP);
    expect(printed.replaceAll(ZWSP, "")).toBe(`Order at ${url} today`);
    expect(printed).toContain(`https:/${ZWSP}/${ZWSP}www.${ZWSP}`);
    expect(printed).toContain(`reseller_${ZWSP}documents`);
  });

  it("softens a long address inside a link run too", () => {
    const email = "orders.and.invoices@very-long-farm-name.test";
    const [run] = styledRuns(`<p><a href="mailto:${email}">${email}</a></p>`);
    expect(run.text).toContain(`@${ZWSP}`);
    expect(run.text!.replaceAll(ZWSP, "")).toBe(email);
  });

  it("leaves short words alone", () => {
    const [printed] = paragraphs("<p>Visit farm.test or call +43-1-234</p>");
    expect(printed).not.toContain(ZWSP);
  });

  it("parses the same HTML the same way every time", () => {
    const html = "<p><strong>a</strong></p><p>b</p>";
    expect(paragraphs(html)).toEqual(["a", "b"]);
    expect(paragraphs(html)).toEqual(["a", "b"]);
  });
});
