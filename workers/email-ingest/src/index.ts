export interface Env {
  APP_INGEST_URL: string;
  INGEST_WEBHOOK_SECRET: string;
  PUBLIC_MAIL_DOMAIN?: string;
  PUBLIC_MAIL_DOMAINS?: string;
  MAX_RAW_BYTES?: string;
  WORKER_ENVIRONMENT?: string;
}

type IngestPayload = {
  to_address: string;
  from_address: string | null;
  subject: string | null;
  provider_message_id: string;
  internet_message_id: string | null;
  source_provider: "cloudflare-email-routing";
  received_at: string | null;
  body_text: string | null;
  body_html: string | null;
  raw_payload: {
    envelope_from: string;
    envelope_to: string;
    headers: Record<string, string>;
    raw_size: number;
    raw_sha256: string;
    raw_excerpt: string;
  };
  has_attachments: boolean;
};

const DEFAULT_MAX_RAW_BYTES = 1024 * 1024;
const HEADER_BODY_SPLIT_RE = /\r?\n\r?\n/;
const TEXT_PART_RE = /Content-Type:\s*text\/plain(?:;[^\r\n]*)?[\s\S]*?(?=\r?\n--[^\r\n]+|$)/i;
const HTML_PART_RE = /Content-Type:\s*text\/html(?:;[^\r\n]*)?[\s\S]*?(?=\r?\n--[^\r\n]+|$)/i;
const GENERATED_DOMAIN_PREFIXES = [
  "atlas",
  "aurora",
  "beacon",
  "blaze",
  "bloom",
  "breeze",
  "byte",
  "cipher",
  "cloud",
  "comet",
  "cosmo",
  "dash",
  "delta",
  "drift",
  "echo",
  "ember",
  "flare",
  "flux",
  "forge",
  "glide",
  "glow",
  "grid",
  "halo",
  "hyper",
  "ion",
  "jet",
  "lumen",
  "matrix",
  "micro",
  "nano",
  "neon",
  "nova",
  "orbit",
  "pixel",
  "pulse",
  "quantum",
  "radar",
  "relay",
  "ripple",
  "rocket",
  "signal",
  "spark",
  "swift",
  "sync",
  "titan",
  "vector",
  "vivid",
  "vortex",
  "wave",
  "zen",
] as const;

function normalizeAddress(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const match = value.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return match ? match[0].toLowerCase() : null;
}

function normalizeDomains(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean))];
}

function generateDomainVariants(baseDomain: string | undefined): string[] {
  const clean = baseDomain?.trim().toLowerCase();
  if (!clean || !clean.includes(".")) {
    return [];
  }

  return GENERATED_DOMAIN_PREFIXES.map((prefix) => `${prefix}.${clean}`);
}

function parseAllowedDomains(env: Env): string[] {
  const csvValues = normalizeDomains((env.PUBLIC_MAIL_DOMAINS ?? "").split(","));
  if (csvValues.length) {
    return normalizeDomains([...csvValues, ...generateDomainVariants(csvValues[0])]);
  }

  const singleDomain = env.PUBLIC_MAIL_DOMAIN?.trim().toLowerCase();
  return singleDomain ? normalizeDomains([singleDomain, ...generateDomainVariants(singleDomain)]) : [];
}

function getHeader(headers: Headers, name: string): string | null {
  return headers.get(name) ?? headers.get(name.toLowerCase()) ?? null;
}

function headersToObject(headers: Headers): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of headers.entries()) {
    result[key] = value;
  }
  return result;
}

function parseMaxRawBytes(rawValue: string | undefined): number {
  if (!rawValue) {
    return DEFAULT_MAX_RAW_BYTES;
  }
  const parsed = Number.parseInt(rawValue, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_MAX_RAW_BYTES;
  }
  return parsed;
}

function getMimeBody(part: string): string {
  const split = part.search(HEADER_BODY_SPLIT_RE);
  if (split === -1) {
    return part;
  }
  return part.slice(split).replace(HEADER_BODY_SPLIT_RE, "");
}

function decodeQuotedPrintable(value: string): string {
  return value
    .replace(/=\r?\n/g, "")
    .replace(/=([0-9A-F]{2})/gi, (_, hex: string) => String.fromCharCode(Number.parseInt(hex, 16)));
}

function maybeDecodeBase64(value: string): string {
  const compact = value.replace(/\s+/g, "");
  if (!compact || compact.length % 4 !== 0 || /[^a-z0-9+/=]/i.test(compact)) {
    return value;
  }

  try {
    return atob(compact);
  } catch {
    return value;
  }
}

function decodeMimePart(part: string): string {
  const body = getMimeBody(part).trim();
  if (/Content-Transfer-Encoding:\s*base64/i.test(part)) {
    return maybeDecodeBase64(body).trim();
  }
  if (/Content-Transfer-Encoding:\s*quoted-printable/i.test(part)) {
    return decodeQuotedPrintable(body).trim();
  }
  return body.trim();
}

function extractBody(rawEmail: string): { bodyText: string | null; bodyHtml: string | null; hasAttachments: boolean } {
  const textMatch = rawEmail.match(TEXT_PART_RE);
  const htmlMatch = rawEmail.match(HTML_PART_RE);
  const hasAttachments = /Content-Disposition:\s*attachment/i.test(rawEmail);

  if (textMatch || htmlMatch) {
    return {
      bodyText: textMatch ? decodeMimePart(textMatch[0]) : null,
      bodyHtml: htmlMatch ? decodeMimePart(htmlMatch[0]) : null,
      hasAttachments,
    };
  }

  const splitIndex = rawEmail.search(HEADER_BODY_SPLIT_RE);
  const body = splitIndex === -1 ? rawEmail : rawEmail.slice(splitIndex).replace(HEADER_BODY_SPLIT_RE, "");
  return {
    bodyText: decodeMimePart(body),
    bodyHtml: null,
    hasAttachments,
  };
}

function parseReceivedAt(headers: Headers): string | null {
  const dateHeader = getHeader(headers, "Date");
  if (!dateHeader) {
    return null;
  }

  const timestamp = Date.parse(dateHeader);
  if (Number.isNaN(timestamp)) {
    return null;
  }

  return new Date(timestamp).toISOString();
}

async function sha256Hex(value: string): Promise<string> {
  const encoded = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function buildProviderMessageId(message: ForwardableEmailMessage, rawHash: string): Promise<string> {
  const messageId = getHeader(message.headers, "Message-ID") ?? getHeader(message.headers, "Message-Id");
  if (messageId) {
    return messageId.trim();
  }

  const date = getHeader(message.headers, "Date") ?? "";
  const subject = getHeader(message.headers, "Subject") ?? "";
  return sha256Hex(`${message.from}|${message.to}|${date}|${subject}|${message.rawSize}|${rawHash}`);
}

async function readRawEmail(message: ForwardableEmailMessage, maxRawBytes: number): Promise<string> {
  if (message.rawSize > maxRawBytes) {
    throw new Error(`message raw size ${message.rawSize} exceeds limit ${maxRawBytes}`);
  }
  return new Response(message.raw).text();
}

async function postToIngest(payload: IngestPayload, env: Env): Promise<Response> {
  return fetch(env.APP_INGEST_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Ingest-Webhook-Secret": env.INGEST_WEBHOOK_SECRET,
    },
    body: JSON.stringify(payload),
  });
}

async function handleEmail(message: ForwardableEmailMessage, env: Env): Promise<void> {
  const toAddress = normalizeAddress(message.to);
  const fromAddress = normalizeAddress(message.from);
  if (!toAddress) {
    message.setReject("Invalid recipient address");
    return;
  }

  const allowedDomains = parseAllowedDomains(env);
  if (allowedDomains.length) {
    const domain = toAddress.split("@", 2)[1];
    if (!allowedDomains.includes(domain)) {
      message.setReject("Recipient domain is not served here");
      return;
    }
  }

  const maxRawBytes = parseMaxRawBytes(env.MAX_RAW_BYTES);
  if (message.rawSize > maxRawBytes) {
    message.setReject("Message is too large for this temporary inbox");
    return;
  }

  const rawEmail = await readRawEmail(message, maxRawBytes);
  const rawHash = await sha256Hex(rawEmail);
  const { bodyText, bodyHtml, hasAttachments } = extractBody(rawEmail);
  const providerMessageId = await buildProviderMessageId(message, rawHash);

  const payload: IngestPayload = {
    to_address: toAddress,
    from_address: fromAddress,
    subject: getHeader(message.headers, "Subject"),
    provider_message_id: providerMessageId,
    internet_message_id: getHeader(message.headers, "Message-ID") ?? getHeader(message.headers, "Message-Id"),
    source_provider: "cloudflare-email-routing",
    received_at: parseReceivedAt(message.headers),
    body_text: bodyText,
    body_html: bodyHtml,
    raw_payload: {
      envelope_from: message.from,
      envelope_to: message.to,
      headers: headersToObject(message.headers),
      raw_size: message.rawSize,
      raw_sha256: rawHash,
      raw_excerpt: rawEmail.slice(0, 4096),
    },
    has_attachments: hasAttachments,
  };

  const response = await postToIngest(payload, env);
  if (response.ok) {
    return;
  }

  const responseText = await response.text();
  throw new Error(`ingest endpoint failed with ${response.status}: ${responseText.slice(0, 300)}`);
}

export default {
  async fetch(): Promise<Response> {
    return Response.json({
      status: "ok",
      service: "tempmail-email-ingest",
    });
  },

  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    await handleEmail(message, env);
  },
} satisfies ExportedHandler<Env>;
