import type { CompanyTaxReturnPayloadField } from "./company-tax-return.ts";

type AuthorityDocument = CompanyTaxReturnPayloadField["authorityDocument"];

type XmlNode = {
  key: string;
  name: string;
  children: XmlNode[];
  value?: string | number | boolean;
};

const documentConfig: Record<AuthorityDocument, { root: string; namespace: string }> = {
  skattemeldingUpersonlig: {
    root: "skattemelding",
    namespace: "urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5",
  },
  naeringsspesifikasjon: {
    root: "naeringsspesifikasjon",
    namespace: "urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6",
  },
};

export function renderCompanyTaxReturnXml(fields: CompanyTaxReturnPayloadField[]) {
  return {
    skattemeldingXml: renderAuthorityDocument("skattemeldingUpersonlig", fields),
    naeringsspesifikasjonXml: renderAuthorityDocument("naeringsspesifikasjon", fields),
  };
}

function renderAuthorityDocument(
  authorityDocument: AuthorityDocument,
  fields: CompanyTaxReturnPayloadField[],
) {
  const config = documentConfig[authorityDocument];
  const root: XmlNode = { key: config.root, name: config.root, children: [] };
  for (const field of fields.filter((candidate) => candidate.authorityDocument === authorityDocument)) {
    const segments = parsePath(field.path);
    if (segments[0]?.name === config.root) {
      segments.shift();
    }
    if (!segments.length) {
      throw new Error(`XML-felt mangler sti under ${config.root}.`);
    }
    insertValue(root, segments, field.value);
  }
  return `<?xml version="1.0" encoding="UTF-8"?>\n${renderNode(root, 0, config.namespace)}\n`;
}

function parsePath(path: string) {
  if (!path.trim()) {
    throw new Error("XML-felt mangler sti.");
  }
  return path.split(".").map((raw) => {
    const match = /^([A-Za-z][A-Za-z0-9]*)(?:\[(\d+)\])?$/.exec(raw);
    if (!match) {
      throw new Error(`Ugyldig XML-feltsti: ${path}`);
    }
    const name = match[1];
    const index = match[2] === undefined ? null : Number(match[2]);
    return { name, key: index === null ? name : `${name}[${index}]` };
  });
}

function insertValue(
  parent: XmlNode,
  segments: Array<{ name: string; key: string }>,
  value: string | number | boolean,
) {
  const [segment, ...rest] = segments;
  let child = parent.children.find((candidate) => candidate.key === segment.key);
  if (!child) {
    child = { key: segment.key, name: segment.name, children: [] };
    parent.children.push(child);
  }
  if (!rest.length) {
    if (child.children.length || child.value !== undefined) {
      throw new Error(`XML-felt er duplisert: ${segment.key}`);
    }
    child.value = value;
    return;
  }
  if (child.value !== undefined) {
    throw new Error(`XML-felt brukes både som verdi og gruppe: ${segment.key}`);
  }
  insertValue(child, rest, value);
}

function renderNode(node: XmlNode, depth: number, namespace?: string): string {
  const indentation = "  ".repeat(depth);
  const namespaceAttribute = namespace ? ` xmlns="${namespace}"` : "";
  if (node.value !== undefined) {
    return `${indentation}<${node.name}${namespaceAttribute}>${escapeXml(valueText(node.value))}</${node.name}>`;
  }
  const children = node.children.map((child) => renderNode(child, depth + 1)).join("\n");
  if (!children) {
    return `${indentation}<${node.name}${namespaceAttribute}/>`;
  }
  return `${indentation}<${node.name}${namespaceAttribute}>\n${children}\n${indentation}</${node.name}>`;
}

function valueText(value: string | number | boolean) {
  return typeof value === "boolean" ? (value ? "true" : "false") : String(value);
}

function escapeXml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
