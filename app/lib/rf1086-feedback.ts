import { SaxesParser, type SaxesTagNS } from "saxes";

export const RF1086_MAX_FEEDBACK_BYTES = 10 * 1024 * 1024;

export const RF1086_FEEDBACK_NAMESPACES = {
  "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2": "innsendingstilbakemelding-v2",
  "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:leveransetilbakemelding:v2": "leveransetilbakemelding-v2",
} as const;

export type Rf1086FeedbackClassification = "accepted" | "rejected" | "action_required";
export type Rf1086FeedbackSchema = typeof RF1086_FEEDBACK_NAMESPACES[keyof typeof RF1086_FEEDBACK_NAMESPACES] | "unknown";
export type Rf1086FeedbackResult = {
  classification: Rf1086FeedbackClassification;
  schema: Rf1086FeedbackSchema;
  transmissionId: string | null;
};

const ACTION_REQUIRED: Rf1086FeedbackResult = {
  classification: "action_required",
  schema: "unknown",
  transmissionId: null,
};

type CapturedField = "leveransestatus" | "forsendelseid" | "inntektsaar";

function expectedParent(schema: Exclude<Rf1086FeedbackSchema, "unknown">, field: CapturedField) {
  if (field === "forsendelseid") return "innsending";
  if (field === "inntektsaar") return "leveranse";
  return schema === "innsendingstilbakemelding-v2" ? "leveranse" : "leveranseoppsummering";
}

export function classifyRf1086Feedback(
  bytes: Uint8Array,
  context: { forsendelseId: string; incomeYear: number },
): Rf1086FeedbackResult {
  if (
    !(bytes instanceof Uint8Array)
    || bytes.byteLength < 1
    || bytes.byteLength > RF1086_MAX_FEEDBACK_BYTES
    || !context.forsendelseId
    || !Number.isInteger(context.incomeYear)
  ) {
    return ACTION_REQUIRED;
  }

  let xml: string;
  try {
    xml = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return ACTION_REQUIRED;
  }
  if (/<!\s*(?:DOCTYPE|ENTITY)\b/iu.test(xml)) return ACTION_REQUIRED;

  let schema: Rf1086FeedbackSchema = "unknown";
  let rootNamespace = "";
  let invalid = false;
  let depth = 0;
  const elementStack: string[] = [];
  const captures: Partial<Record<CapturedField, string[]>> = {};
  let activeCapture: { field: CapturedField; depth: number; text: string } | null = null;

  try {
    const parser = new SaxesParser({ xmlns: true, position: false });
    parser.on("doctype", () => {
      invalid = true;
    });
    parser.on("error", () => {
      invalid = true;
    });
    parser.on("opentag", (tag: SaxesTagNS) => {
      depth += 1;
      const local = tag.local;
      if (depth === 1) {
        rootNamespace = tag.uri;
        const mappedSchema = Object.prototype.hasOwnProperty.call(RF1086_FEEDBACK_NAMESPACES, rootNamespace)
          ? RF1086_FEEDBACK_NAMESPACES[rootNamespace as keyof typeof RF1086_FEEDBACK_NAMESPACES]
          : undefined;
        schema = mappedSchema ?? "unknown";
        if (local !== "tilbakemelding" || !mappedSchema) invalid = true;
      } else if (tag.uri !== rootNamespace) {
        invalid = true;
      }

      if (activeCapture) invalid = true;
      const field = local as CapturedField;
      if (field === "leveransestatus" || field === "forsendelseid" || field === "inntektsaar") {
        const parent = elementStack.at(-1);
        if (schema === "unknown" || parent !== expectedParent(schema, field)) {
          invalid = true;
        }
        activeCapture = { field, depth, text: "" };
      }
      elementStack.push(local);
    });
    parser.on("text", (text: string) => {
      if (activeCapture) {
        activeCapture.text += text;
        if (activeCapture.text.length > 500) invalid = true;
      }
    });
    parser.on("cdata", () => {
      if (activeCapture) invalid = true;
    });
    parser.on("closetag", () => {
      if (activeCapture?.depth === depth) {
        const values = captures[activeCapture.field] ?? [];
        values.push(activeCapture.text.trim());
        captures[activeCapture.field] = values;
        activeCapture = null;
      }
      elementStack.pop();
      depth -= 1;
    });
    parser.write(xml).close();
  } catch {
    invalid = true;
  }

  const statuses = captures.leveransestatus ?? [];
  const transmissionIds = captures.forsendelseid ?? [];
  const incomeYears = captures.inntektsaar ?? [];
  if (
    invalid
    || schema === "unknown"
    || depth !== 0
    || statuses.length !== 1
    || !["godkjent", "avvist"].includes(statuses[0])
    || transmissionIds.length > 1
    || incomeYears.length > 1
    || (transmissionIds.length === 1 && transmissionIds[0] !== context.forsendelseId)
    || (incomeYears.length === 1 && incomeYears[0] !== String(context.incomeYear))
  ) {
    return {
      classification: "action_required",
      schema,
      transmissionId: transmissionIds.length === 1 ? transmissionIds[0] : null,
    };
  }

  return {
    classification: statuses[0] === "godkjent" ? "accepted" : "rejected",
    schema,
    transmissionId: transmissionIds[0] ?? null,
  };
}
