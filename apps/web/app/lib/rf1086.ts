import { spawnSync } from "node:child_process";
import type { CompanyWorkspaceRow, OpeningBalanceSetupRow, OpeningShareholderRow } from "./supabase/server";
import { resolveTalliPythonBinary } from "./python-runtime.ts";

export type Rf1086RenderResult = {
  filing: string;
  status: "ready" | "blocked" | "warning";
  issues: { level: string; code: string; message: string }[];
  preview: string;
  hovedskjemaXml?: string;
  underskjemaXml?: Record<string, string>;
};

export function buildNoActivityRf1086Case(
  company: CompanyWorkspaceRow,
  setup: OpeningBalanceSetupRow,
  shareholders: OpeningShareholderRow[],
) {
  if (!company.postal_code || !/^\d{4}$/.test(company.postal_code)) {
    throw new Error("Selskapet mangler gyldig postnummer fra Brønnøysund før RF-1086 kan bygges.");
  }
  if (shareholders.length === 0) {
    throw new Error("RF-1086 krever minst én aksjonær.");
  }

  return {
    case_id: `persisted-${company.org_number}-${setup.income_year}-${setup.id}`,
    company: {
      org_number: company.org_number,
      name: company.name,
      address: company.address || "Ukjent adresse",
      postal_code: company.postal_code,
      city: company.city || "Ukjent",
      income_year: setup.income_year,
      share_type: "01",
    },
    share_snapshot: {
      previous_share_capital: Number(setup.share_capital),
      current_share_capital: Number(setup.share_capital),
      previous_nominal_value: Number(setup.nominal_value),
      current_nominal_value: Number(setup.nominal_value),
      previous_share_count: Number(setup.share_count),
      current_share_count: Number(setup.share_count),
      previous_paid_in_share_capital: Number(setup.share_capital),
      current_paid_in_share_capital: Number(setup.share_capital),
      previous_paid_in_premium: 0,
      current_paid_in_premium: 0,
    },
    shareholders: shareholders.map((shareholder) => ({
      id: shareholder.id,
      kind: shareholder.shareholder_kind,
      name: shareholder.name,
      national_id: shareholder.national_id,
      org_number: shareholder.org_number,
    })),
    shareholder_snapshots: shareholders.map((shareholder) => ({
      shareholder_id: shareholder.id,
      previous_share_count: Number(shareholder.share_count),
      current_share_count: Number(shareholder.share_count),
    })),
    events: [],
  };
}

export type NoActivityRf1086Case = ReturnType<typeof buildNoActivityRf1086Case>;

type XmlNode = {
  name: string;
  attributes?: Record<string, string>;
  text?: string;
  children?: XmlNode[];
};

function xmlEscape(value: string, attribute = false) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', attribute ? "&quot;" : '"');
}

function xmlValue(value: string | number) {
  if (typeof value !== "number") return value;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(6).replace(/0+$/u, "").replace(/\.$/u, "");
}

function xmlNode(
  name: string,
  attributes: Record<string, string> = {},
  children: XmlNode[] = [],
): XmlNode {
  return { name, attributes, children };
}

function xmlGroup(name: string, groupId: string, children: XmlNode[] = []) {
  return xmlNode(name, { gruppeid: groupId }, children);
}

function xmlData(name: string, orid: string, value: string | number): XmlNode {
  return { name, attributes: { orid }, text: xmlValue(value) };
}

function serializeXml(node: XmlNode, depth = 0): string {
  const indent = "  ".repeat(depth);
  const attributes = Object.entries(node.attributes ?? {})
    .map(([key, value]) => ` ${key}="${xmlEscape(value, true)}"`)
    .join("");
  const children = node.children ?? [];
  if (!children.length && node.text === undefined) {
    return `${indent}<${node.name}${attributes} />`;
  }
  if (!children.length) {
    return `${indent}<${node.name}${attributes}>${xmlEscape(node.text ?? "")}</${node.name}>`;
  }
  return [
    `${indent}<${node.name}${attributes}>`,
    ...children.map((child) => serializeXml(child, depth + 1)),
    `${indent}</${node.name}>`,
  ].join("\n");
}

function xmlDocument(root: XmlNode) {
  return `<?xml version="1.0" encoding="UTF-8"?>\n${serializeXml(root)}\n`;
}

function invalidNoActivityCase(filingCase: NoActivityRf1086Case): string | null {
  const { company, share_snapshot: shares, shareholders, shareholder_snapshots: snapshots, events } = filingCase;
  if (!filingCase.case_id) return "case_id is required";
  if (!/^\d{9}$/u.test(company.org_number)) return "company org_number must contain 9 digits";
  if (!/^\d{4}$/u.test(company.postal_code)) return "company postal_code must contain 4 digits";
  if (!Number.isInteger(company.income_year) || company.income_year < 2000 || company.income_year > 2100) {
    return "company income_year must be between 2000 and 2100";
  }
  if (company.share_type !== "01") return "only ordinary share class 01 is supported";
  if (events.length !== 0) return "the serverless RF-1086 renderer only accepts no-activity cases";
  if (!shareholders.length) return "at least one shareholder is required";
  const nonNegativeNumbers = [
    shares.previous_share_capital,
    shares.current_share_capital,
    shares.previous_nominal_value,
    shares.current_nominal_value,
    shares.previous_share_count,
    shares.current_share_count,
    shares.previous_paid_in_share_capital,
    shares.current_paid_in_share_capital,
    shares.previous_paid_in_premium,
    shares.current_paid_in_premium,
  ];
  if (nonNegativeNumbers.some((value) => !Number.isFinite(value) || value < 0)) {
    return "share snapshot values must be non-negative numbers";
  }
  if (![shares.previous_share_count, shares.current_share_count].every(Number.isInteger)) {
    return "share counts must be integers";
  }

  const shareholderIds = new Set(shareholders.map((shareholder) => shareholder.id));
  const snapshotIds = new Set(snapshots.map((snapshot) => snapshot.shareholder_id));
  if (
    shareholderIds.size !== shareholders.length
    || snapshotIds.size !== snapshots.length
    || shareholderIds.size !== snapshotIds.size
    || [...shareholderIds].some((id) => !snapshotIds.has(id))
  ) {
    return "shareholders and shareholder snapshots must contain the same unique ids";
  }
  for (const shareholder of shareholders) {
    if (!shareholder.id || !shareholder.name) return "shareholder id and name are required";
    if (!["norwegian_person", "norwegian_company"].includes(shareholder.kind)) {
      return "shareholder kind must be norwegian_person or norwegian_company";
    }
    if (shareholder.kind === "norwegian_person" && !/^\d{11}$/u.test(shareholder.national_id ?? "")) {
      return "Norwegian personal shareholder requires an 11 digit national_id";
    }
    if (shareholder.kind === "norwegian_company" && !/^\d{9}$/u.test(shareholder.org_number ?? "")) {
      return "Norwegian corporate shareholder requires a 9 digit org_number";
    }
  }
  if (snapshots.some((snapshot) =>
    !Number.isInteger(snapshot.previous_share_count)
    || !Number.isInteger(snapshot.current_share_count)
    || snapshot.previous_share_count < 0
    || snapshot.current_share_count < 0
  )) {
    return "shareholder share counts must be non-negative integers";
  }
  const previousTotal = snapshots.reduce((total, snapshot) => total + snapshot.previous_share_count, 0);
  const currentTotal = snapshots.reduce((total, snapshot) => total + snapshot.current_share_count, 0);
  if (previousTotal !== shares.previous_share_count) {
    return "sum of previous shareholder shares must equal company previous share count";
  }
  if (currentTotal !== shares.current_share_count) {
    return "sum of current shareholder shares must equal company current share count";
  }
  return null;
}

function pairGroup(
  name: string,
  groupId: string,
  previous: [string, string, number],
  current: [string, string, number],
) {
  return xmlGroup(name, groupId, [
    xmlData(previous[0], previous[1], previous[2]),
    xmlData(current[0], current[1], current[2]),
  ]);
}

function buildNoActivityHovedskjema(filingCase: NoActivityRf1086Case) {
  const { company, share_snapshot: shares } = filingCase;
  return xmlDocument(xmlNode("Skjema", {
    skjemanummer: "890",
    spesifikasjonsnummer: "12144",
    blankettnummer: "RF-1086",
    tittel: "Aksjonærregisteroppgaven",
    gruppeid: "2586",
    etatid: "974761076",
  }, [
    xmlGroup("GenerellInformasjon-grp-2587", "2587", [
      xmlGroup("Selskap-grp-2588", "2588", [
        xmlData("EnhetOrganisasjonsnummer-datadef-18", "18", company.org_number),
        xmlData("EnhetNavn-datadef-1", "1", company.name),
        xmlData("EnhetAdresse-datadef-15", "15", company.address),
        xmlData("EnhetPostnummer-datadef-6673", "6673", company.postal_code),
        xmlData("EnhetPoststed-datadef-6674", "6674", company.city),
        xmlData("AksjeType-datadef-17659", "17659", company.share_type),
        xmlData("Inntektsar-datadef-692", "692", company.income_year),
      ]),
      xmlGroup("Kontaktperson-grp-3442", "3442"),
      xmlGroup("AnnenKontaktperson-grp-5384", "5384"),
    ]),
    xmlGroup("Selskapsopplysninger-grp-2589", "2589", [
      pairGroup("AksjekapitalForHeleSelskapet-grp-3443", "3443",
        ["AksjekapitalFjoraret-datadef-7129", "7129", shares.previous_share_capital],
        ["Aksjekapital-datadef-87", "87", shares.current_share_capital]),
      pairGroup("AksjekapitalIDenneAksjeklassen-grp-3444", "3444",
        ["AksjekapitalISINAksjetypeFjoraret-datadef-17663", "17663", shares.previous_share_capital],
        ["AksjekapitalISINAksjetype-datadef-17664", "17664", shares.current_share_capital]),
      pairGroup("PalydendePerAksje-grp-3447", "3447",
        ["AksjeMvPalydendeFjoraret-datadef-23944", "23944", shares.previous_nominal_value],
        ["AksjeMvPalydende-datadef-23945", "23945", shares.current_nominal_value]),
      pairGroup("AntallAksjerIDenneAksjeklassen-grp-3445", "3445",
        ["AksjerMvAntallFjoraret-datadef-29166", "29166", shares.previous_share_count],
        ["AksjerMvAntall-datadef-29167", "29167", shares.current_share_count]),
      pairGroup("InnbetaltAksjekapitalIDenneAksjeklassen-grp-3446", "3446",
        ["AksjekapitalInnbetaltFjoraret-datadef-8020", "8020", shares.previous_paid_in_share_capital],
        ["AksjekapitalInnbetalt-datadef-5867", "5867", shares.current_paid_in_share_capital]),
      pairGroup("InnbetaltOverkursIDenneAksjeklassen-grp-3448", "3448",
        ["AksjeOverkursISINAksjetypeFjoraret-datadef-17662", "17662", shares.previous_paid_in_premium],
        ["AksjeOverkursISINAksjetype-datadef-17661", "17661", shares.current_paid_in_premium]),
    ]),
  ]));
}

function buildNoActivityUnderskjema(
  filingCase: NoActivityRf1086Case,
  snapshot: NoActivityRf1086Case["shareholder_snapshots"][number],
) {
  const shareholder = filingCase.shareholders.find((candidate) => candidate.id === snapshot.shareholder_id)!;
  const shareholderIdentity = shareholder.kind === "norwegian_person"
    ? xmlData("AksjonarFodselsnummer-datadef-1156", "1156", shareholder.national_id!)
    : xmlData("AksjonarOrganisasjonsnummer-datadef-7597", "7597", shareholder.org_number!);
  return xmlDocument(xmlNode("Skjema", {
    skjemanummer: "923",
    spesifikasjonsnummer: "12232",
    blankettnummer: "RF-1086-U",
    tittel: "Aksjonærregisteroppgaven - underskjema",
    gruppeid: "3983",
    etatid: "974761076",
  }, [
    xmlGroup("SelskapsOgAksjonaropplysninger-grp-3987", "3987", [
      xmlGroup("Selskapsidentifikasjon-grp-3986", "3986", [
        xmlData("EnhetOrganisasjonsnummer-datadef-18", "18", filingCase.company.org_number),
        xmlData("AksjeType-datadef-17659", "17659", filingCase.company.share_type),
        xmlData("Inntektsar-datadef-692", "692", filingCase.company.income_year),
      ]),
      xmlGroup("NorskUtenlandskAksjonar-grp-3988", "3988", [
        shareholderIdentity,
        xmlData("AksjonarNavn-datadef-1153", "1153", shareholder.name),
        xmlGroup("Adresse-grp-7722", "7722"),
      ]),
    ]),
    xmlGroup("AntallAksjerUtbytteOgTilbakebetalingAvTidligereInnbetaltKapit-grp-3990", "3990", [
      xmlGroup("AntallAksjerPerAksjonar-grp-3989", "3989", [
        xmlData("AksjerAntallFjoraret-datadef-29168", "29168", snapshot.previous_share_count),
        xmlData("AksjonarAksjerAntall-datadef-17741", "17741", snapshot.current_share_count),
      ]),
    ]),
  ]));
}

function amount(value: number) {
  return Number.isInteger(value) ? `${value} kr` : `${value.toFixed(2)} kr`;
}

function noActivityPreview(filingCase: NoActivityRf1086Case) {
  const { company, share_snapshot: shares } = filingCase;
  const shareholdersById = new Map(filingCase.shareholders.map((shareholder) => [shareholder.id, shareholder]));
  return [
    `Aksjonærregisteroppgaven ${company.income_year}`,
    `Selskap: ${company.name} (${company.org_number})`,
    `Aksjeklasse: ordinære (${company.share_type})`,
    "",
    "Selskapsnivå:",
    `- Aksjekapital 1. januar: ${amount(shares.previous_share_capital)}`,
    `- Aksjekapital 31. desember: ${amount(shares.current_share_capital)}`,
    `- Antall aksjer 1. januar: ${shares.previous_share_count}`,
    `- Antall aksjer 31. desember: ${shares.current_share_count}`,
    "",
    "Aksjonærer:",
    ...filingCase.shareholder_snapshots.map((snapshot) => {
      const shareholder = shareholdersById.get(snapshot.shareholder_id)!;
      return `- ${shareholder.name}: ${snapshot.previous_share_count} aksjer 1. januar, ${snapshot.current_share_count} aksjer 31. desember`;
    }),
    "",
  ].join("\n");
}

/**
 * Deterministic serverless renderer for the production pilot's exact
 * `rf1086_no_activity_v1` profile. It intentionally rejects eventful cases;
 * those remain outside the controlled live scope.
 */
export function renderRf1086Preview(filingCase: NoActivityRf1086Case): Rf1086RenderResult {
  const invalid = invalidNoActivityCase(filingCase);
  if (invalid) {
    return {
      filing: "aksjonærregisteroppgaven",
      status: "blocked",
      issues: [{ level: "error", code: "invalid_case", message: invalid }],
      preview: `RF-1086 kunne ikke genereres: ${invalid}\n`,
    };
  }
  return {
    filing: "aksjonærregisteroppgaven",
    status: "ready",
    issues: [],
    preview: noActivityPreview(filingCase),
    hovedskjemaXml: buildNoActivityHovedskjema(filingCase),
    underskjemaXml: Object.fromEntries(
      filingCase.shareholder_snapshots.map((snapshot) => [
        snapshot.shareholder_id,
        buildNoActivityUnderskjema(filingCase, snapshot),
      ]),
    ),
  };
}

export function renderRf1086PreviewWithPython(filingCase: unknown): Rf1086RenderResult {
  const python = resolveTalliPythonBinary();
  const result = spawnSync(python, ["-m", "holding_cli.main", "render-rf1086-preview", "--stdin-json"], {
    input: JSON.stringify(filingCase),
    encoding: "utf8",
    env: process.env,
  });
  if (result.error) {
    throw result.error;
  }
  const stdout = result.stdout.trim();
  if (!stdout) {
    throw new Error(result.stderr.trim() || "RF-1086 engine produced no output.");
  }
  const parsed = JSON.parse(stdout) as Rf1086RenderResult;
  if (result.status !== 0 && parsed.status !== "blocked") {
    throw new Error(result.stderr.trim() || "RF-1086 engine failed.");
  }
  return parsed;
}
