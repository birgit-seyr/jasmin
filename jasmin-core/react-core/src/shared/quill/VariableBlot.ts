/**
 * Quill custom embed blot used by the email-template editor.
 *
 * Renders inserted template variables (e.g. ``user.first_name``) as
 * read-only "chips" displaying a human-friendly label
 * (``Vorname Mitglied``). On save, the chip is converted back to its
 * raw ``{{ user.first_name }}`` placeholder so the backend renderer can
 * substitute it.
 *
 * Importing this module registers the blot with Quill (side-effect).
 */
import { Quill } from "react-quill-new";

const Embed: any = Quill.import("blots/embed");

interface VariableValue {
  name: string;
  label: string;
}

class VariableBlot extends Embed {
  static blotName = "tplVar";
  static tagName = "span";
  static className = "email-tpl-var";

  static create(value: VariableValue) {
    const node: HTMLElement = super.create(value);
    node.setAttribute("data-var", value.name);
    node.setAttribute("contenteditable", "false");
    node.textContent = value.label || `{{ ${value.name} }}`;
    return node;
  }

  static value(node: HTMLElement): VariableValue {
    return {
      name: node.getAttribute("data-var") || "",
      label: node.textContent || "",
    };
  }
}

Quill.register(VariableBlot, true);

const TPL_VAR_RE =
  /<span[^>]*class="[^"]*email-tpl-var[^"]*"[^>]*data-var="([^"]+)"[^>]*>[^<]*<\/span>/g;

/**
 * Convert chips in editor HTML back to raw ``{{ name }}`` placeholders.
 * Use this before saving / previewing.
 */
export function chipsToPlaceholders(html: string): string {
  if (!html) return html;
  return html.replace(TPL_VAR_RE, (_match, name) => `{{ ${name} }}`);
}

/**
 * Convert raw ``{{ name }}`` placeholders into chip HTML using a label
 * lookup. Use this when loading content into the editor.
 */
export function placeholdersToChips(
  html: string,
  labels: Record<string, string>,
): string {
  if (!html) return html;
  return html.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_m, name: string) => {
    const label = labels[name] || `{{ ${name} }}`;
    // Escape for HTML — labels are plain text from the backend registry.
    const safe = label
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return `<span class="email-tpl-var" data-var="${name}" contenteditable="false">${safe}</span>`;
  });
}

/**
 * Convert a plain-text value (with ``{{ name }}`` placeholders) to chip
 * HTML — used by the single-line subject editor.
 */
export function plainTextToChips(
  text: string,
  labels: Record<string, string>,
): string {
  if (!text) return "";
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return placeholdersToChips(escaped, labels);
}

/**
 * Convert chip HTML from the single-line subject editor back to a
 * plain-text value with ``{{ name }}`` placeholders.
 */
export function chipsToPlainText(html: string): string {
  if (!html) return "";
  // First convert chips → placeholders so they survive tag stripping.
  const withPlaceholders = chipsToPlaceholders(html);
  // Strip all remaining HTML tags Quill may have added (<p>, <br>, …).
  const stripped = withPlaceholders
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/p>\s*<p[^>]*>/gi, " ")
    .replace(/<[^>]+>/g, "");
  // Decode the small set of entities we produced.
  return stripped
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .trim();
}
