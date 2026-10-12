import { expect, request, type APIRequestContext } from "@playwright/test";
import { MAILHOG_URL } from "./env";

/** The parts of a MailHog message the flows read. */
export interface Mail {
  id: string;
  subject: string;
  /** The decoded text of every part (plain and HTML), concatenated. */
  body: string;
}

interface MailHogMessage {
  ID: string;
  Content: {
    Headers: Record<string, string[] | undefined>;
    Body: string;
  };
  MIME: { Parts: MailHogPart[] | null } | null;
}

interface MailHogPart {
  Headers: Record<string, string[] | undefined>;
  Body: string;
  MIME: { Parts: MailHogPart[] | null } | null;
}

interface MailHogSearch {
  items: MailHogMessage[];
}

function header(
  headers: Record<string, string[] | undefined>,
  name: string,
): string {
  return headers[name]?.[0] ?? "";
}

function decodeQuotedPrintable(text: string): string {
  const joined = text.replace(/=\r?\n/g, "");
  const bytes: number[] = [];
  for (let index = 0; index < joined.length; index += 1) {
    const hex = joined.slice(index + 1, index + 3);
    if (joined[index] === "=" && /^[0-9A-F]{2}$/i.test(hex)) {
      bytes.push(parseInt(hex, 16));
      index += 2;
    } else {
      bytes.push(...Buffer.from(joined[index], "utf8"));
    }
  }
  return Buffer.from(bytes).toString("utf8");
}

function decodePart(headers: Record<string, string[] | undefined>, body: string): string {
  const encoding = header(headers, "Content-Transfer-Encoding").toLowerCase();
  if (encoding === "base64") return Buffer.from(body, "base64").toString("utf8");
  if (encoding === "quoted-printable") return decodeQuotedPrintable(body);
  return body;
}

function leafTexts(part: MailHogPart): string[] {
  const children = part.MIME?.Parts;
  if (children?.length) return children.flatMap(leafTexts);
  return [decodePart(part.Headers, part.Body)];
}

/** An RFC 2047 encoded-word subject (``=?utf-8?b?...?=``) in plain text. */
function decodeSubject(subject: string): string {
  return subject.replace(
    /=\?[^?]+\?([BbQq])\?([^?]*)\?=/g,
    (_, kind: string, text: string) =>
      kind.toUpperCase() === "B"
        ? Buffer.from(text, "base64").toString("utf8")
        : decodeQuotedPrintable(text.replace(/_/g, " ")),
  );
}

function toMail(message: MailHogMessage): Mail {
  const parts = message.MIME?.Parts;
  const texts = parts?.length
    ? parts.flatMap(leafTexts)
    : [decodePart(message.Content.Headers, message.Content.Body)];
  return {
    id: message.ID,
    subject: decodeSubject(header(message.Content.Headers, "Subject")),
    body: texts.join("\n"),
  };
}

async function withMailHog<T>(
  use: (api: APIRequestContext) => Promise<T>,
): Promise<T> {
  const api = await request.newContext({ baseURL: MAILHOG_URL });
  try {
    return await use(api);
  } finally {
    await api.dispose();
  }
}

async function messagesTo(
  api: APIRequestContext,
  address: string,
): Promise<MailHogMessage[]> {
  const response = await api.get("/api/v2/search", {
    params: { kind: "to", query: address, limit: 50 },
  });
  expect(response.status(), `MailHog search for ${address}`).toBe(200);
  return ((await response.json()) as MailHogSearch).items;
}

/**
 * Deletes every mail to ``address``, so a later {@link waitForMail} can only
 * find the one the test is about to send. The other mail in the dev MailHog
 * stays.
 */
export async function clearMailbox(address: string): Promise<void> {
  await withMailHog(async (api) => {
    for (const message of await messagesTo(api, address)) {
      const response = await api.delete(`/api/v1/messages/${message.ID}`);
      expect(response.ok(), `delete MailHog message ${message.ID}`).toBe(true);
    }
  });
}

/**
 * Polls MailHog until a mail to ``address`` arrives and returns the newest.
 * Mail can go out through the Huey worker, so it lands some time after the
 * request that queued it.
 */
export async function waitForMail(
  address: string,
  { timeout = 30_000 }: { timeout?: number } = {},
): Promise<Mail> {
  return withMailHog(async (api) => {
    let newest: MailHogMessage | undefined;
    await expect
      .poll(
        async () => {
          [newest] = await messagesTo(api, address);
          return newest !== undefined;
        },
        { message: `a mail to ${address} in MailHog`, timeout },
      )
      .toBe(true);
    if (!newest) throw new Error(`No mail to ${address}`);
    return toMail(newest);
  });
}

/** Every ``http(s)://`` link in a mail body, in order, without duplicates. */
export function linksIn(mail: Mail): string[] {
  const links = mail.body.match(/https?:\/\/[^\s"'<>]+/g) ?? [];
  return [...new Set(links.map((link) => link.replace(/&amp;/g, "&")))];
}
