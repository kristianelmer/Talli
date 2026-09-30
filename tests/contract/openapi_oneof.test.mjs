import assert from "node:assert/strict";
import test from "node:test";

import {
  assertCompatible,
  assertValueMatchesSchema,
  validateOpenApiDocument,
} from "../../scripts/check-openapi-contract.mjs";

function fixture() {
  const variant = (tag) => ({
    type: "object",
    additionalProperties: false,
    required: ["type", "amount"],
    properties: {
      type: { type: "string", const: tag },
      amount: { type: "string", pattern: "^[0-9]+$" },
      allocations: { type: "array", items: { $ref: "#/components/schemas/Allocation" } },
    },
  });
  return {
    openapi: "3.1.0",
    info: { title: "Discriminated events", version: "1.0.0" },
    paths: {
      "/source": {
        get: {
          operationId: "readSource",
          responses: { 200: { content: { "application/json": { schema: {
            type: "object",
            required: ["currentSource"],
            properties: { currentSource: { anyOf: [
              { type: "null" },
              { type: "array", items: { $ref: "#/components/schemas/Event" } },
            ] } },
          } } } } },
        },
      },
    },
    components: { schemas: {
      Event: {
        oneOf: [{ $ref: "#/components/schemas/Formation" }, { $ref: "#/components/schemas/Dividend" }],
        discriminator: {
          propertyName: "type",
          mapping: {
            formation: "#/components/schemas/Formation",
            dividend: "#/components/schemas/Dividend",
          },
        },
      },
      Formation: variant("formation"),
      Dividend: variant("dividend"),
      Allocation: { type: "object", required: ["holder"], properties: { holder: { type: "string" } } },
    } },
  };
}

const event = (document) => document.components.schemas.Event;
const response = (document) => document.paths["/source"].get.responses[200].content["application/json"].schema;

test("discriminated oneOf supports unchanged contracts and reordered alternatives/required properties", () => {
  const baseline = fixture();
  validateOpenApiDocument(baseline);
  assertCompatible(baseline, structuredClone(baseline));
  const current = structuredClone(baseline);
  event(current).oneOf.reverse();
  response(current).properties.currentSource.anyOf.reverse();
  current.components.schemas.Formation.required.reverse();
  assertCompatible(baseline, current);
});

test("union ordering preserves distinct Unicode bytes even when locale collation considers tags equal", () => {
  const baseline = fixture();
  baseline.components.schemas.Formation.properties.type.const = "é";
  baseline.components.schemas.Dividend.properties.type.const = "e\u0301";
  event(baseline).discriminator.mapping = {
    "é": "#/components/schemas/Formation",
    "e\u0301": "#/components/schemas/Dividend",
  };
  const current = structuredClone(baseline);
  event(current).oneOf.reverse();
  assertCompatible(baseline, current);
});

for (const [name, change] of [
  ["changed discriminator", (d) => {
    event(d).discriminator.propertyName = "kind";
    for (const name of ["Formation", "Dividend"]) {
      const variant = d.components.schemas[name];
      variant.properties.kind = variant.properties.type;
      delete variant.properties.type;
      variant.required = ["kind", "amount"];
    }
  }],
  ["changed const", (d) => {
    d.components.schemas.Formation.properties.type.const = "incorporation";
    event(d).discriminator.mapping.incorporation = event(d).discriminator.mapping.formation;
    delete event(d).discriminator.mapping.formation;
  }],
  ["changed variant property", (d) => { d.components.schemas.Formation.properties.amount.type = "integer"; }],
  ["changed variant constraint", (d) => { d.components.schemas.Formation.properties.amount.pattern = "^[0-9.]+$"; }],
  ["changed unknown keyword", (d) => { d.components.schemas.Formation["x-domain-check"] = "changed"; }],
  ["changed nested referenced schema", (d) => { d.components.schemas.Allocation.properties.holder.type = "integer"; }],
  ["removed required variant property", (d) => { d.components.schemas.Formation.required = ["type"]; }],
  ["removed alternative", (d) => { event(d).oneOf.pop(); delete event(d).discriminator.mapping.dividend; }],
  ["added alternative", (d) => {
    d.components.schemas.Sale = structuredClone(d.components.schemas.Formation);
    d.components.schemas.Sale.properties.type.const = "sale";
    event(d).oneOf.push({ $ref: "#/components/schemas/Sale" });
    event(d).discriminator.mapping.sale = "#/components/schemas/Sale";
  }],
  ["oneOf replaced by anyOf", (d) => {
    event(d).anyOf = event(d).oneOf;
    delete event(d).oneOf;
    delete event(d).discriminator;
  }],
]) {
  test(`response compatibility rejects ${name}, including beneath nullable wrappers`, () => {
    const baseline = fixture();
    const current = structuredClone(baseline);
    change(current);
    validateOpenApiDocument(current);
    assert.throws(() => assertCompatible(baseline, current), /changed union schema/);
    // Also check a top-level oneOf, without the nullable envelope.
    baseline.paths["/source"].get.responses[200].content["application/json"].schema = { $ref: "#/components/schemas/Event" };
    current.paths["/source"].get.responses[200].content["application/json"].schema = { $ref: "#/components/schemas/Event" };
    assert.throws(() => assertCompatible(baseline, current), /changed union schema/);
  });
}

for (const [name, change] of [
  ["empty alternatives", (d) => { event(d).oneOf = []; }],
  ["non-array alternatives", (d) => { event(d).oneOf = {}; }],
  ["null alternatives", (d) => { event(d).oneOf = null; }],
  ["missing discriminator", (d) => { delete event(d).discriminator; }],
  ["missing mapping", (d) => { delete event(d).discriminator.mapping; }],
  ["missing mapping entry", (d) => { delete event(d).discriminator.mapping.formation; }],
  ["extra mapping entry", (d) => { event(d).discriminator.mapping.extra = "#/components/schemas/Formation"; }],
  ["wrong mapping target", (d) => { event(d).discriminator.mapping.formation = "#/components/schemas/Dividend"; }],
  ["inline alternatives", (d) => { event(d).oneOf[0] = d.components.schemas.Formation; }],
  ["reference siblings", (d) => { event(d).oneOf[0].description = "cannot be ignored"; }],
  ["external reference", (d) => { event(d).oneOf[0].$ref = "https://example.invalid/schema"; }],
  ["missing reference", (d) => { event(d).oneOf[0].$ref = "#/components/schemas/Missing"; }],
  ["non-object variant", (d) => { d.components.schemas.Formation.type = "string"; }],
  ["optional discriminator", (d) => { d.components.schemas.Formation.required = ["amount"]; }],
  ["non-string discriminator", (d) => { d.components.schemas.Formation.properties.type = { type: "integer", const: 1 }; }],
  ["non-const discriminator", (d) => { delete d.components.schemas.Formation.properties.type.const; }],
  ["overlapping alternative", (d) => { event(d).oneOf.push(event(d).oneOf[0]); }],
  ["overlapping discriminator const", (d) => { d.components.schemas.Dividend.properties.type.const = "formation"; }],
  ["union sibling assertions", (d) => { event(d).not = { type: "null" }; }],
  ["combined oneOf and anyOf", (d) => { event(d).anyOf = [{ type: "object" }]; }],
]) {
  test(`validation rejects unsupported or ambiguous oneOf: ${name}`, () => {
    const document = fixture();
    change(document);
    assert.throws(() => validateOpenApiDocument(document));
  });
}

test("runtime oneOf matching accepts one tag and rejects missing, unknown, and malformed alternatives", () => {
  const document = fixture();
  for (const type of ["formation", "dividend"]) {
    assertValueMatchesSchema(document, event(document), { type, amount: "10", allocations: [{ holder: "owner" }] });
  }
  for (const value of [null, [], {}, { type: "sale", amount: "10" }, { type: "formation" },
    { type: "formation", amount: 10 }, { type: "formation", amount: "not-money" },
    { type: "formation", amount: "10", unexpected: true },
    { type: "formation", amount: "10", allocations: [{ holder: 1 }] }]) {
    assert.throws(() => assertValueMatchesSchema(document, event(document), value), /exactly one schema/);
  }
  assertValueMatchesSchema(document, response(document), { currentSource: [{ type: "formation", amount: "10" }] });
  assertValueMatchesSchema(document, response(document), { currentSource: null });
  assert.throws(() => assertValueMatchesSchema(document, response(document), { currentSource: [{ type: "unknown", amount: "10" }] }));
});

test("runtime matching refuses overlapping alternatives instead of treating oneOf as anyOf", () => {
  const document = fixture();
  event(document).oneOf.push(event(document).oneOf[0]);
  assert.throws(() => assertValueMatchesSchema(document, event(document), { type: "formation", amount: "10" }), /ambiguous/);
});

test("request contracts still reject reordered request schemas", () => {
  const baseline = fixture();
  baseline.paths["/source"].get.requestBody = { required: true, content: {
    "application/json": { schema: structuredClone(event(baseline)) },
  } };
  const current = structuredClone(baseline);
  current.paths["/source"].get.requestBody.content["application/json"].schema.oneOf.reverse();
  assert.throws(() => assertCompatible(baseline, current), /request body application\/json changed schema/);
});

test("strict union comparison refuses recursive schemas it cannot safely expand", () => {
  const document = fixture();
  document.components.schemas.Allocation.properties.parent = { $ref: "#/components/schemas/Allocation" };
  const acyclic = fixture();
  assert.throws(() => validateOpenApiDocument(document), /unsupported recursive schema reference/);
  assert.throws(() => assertCompatible(acyclic, document), /unsupported recursive schema reference/);
});

test("runtime alternatives enforce RF numeric bounds and enum values", () => {
  const document = fixture();
  const variant = document.components.schemas.Formation;
  variant.properties.shares = { type: "integer", minimum: 1, maximum: 100 };
  variant.properties.kind = { type: "string", enum: ["ordinary"] };
  for (const extra of [{ shares: 0 }, { shares: 101 }, { shares: 1.5 }, { shares: Infinity }, { kind: "other" }]) {
    assert.throws(() => assertValueMatchesSchema(document, event(document), { type: "formation", amount: "10", ...extra }));
  }
  assertValueMatchesSchema(document, event(document), { type: "formation", amount: "10", shares: 100, kind: "ordinary" });
});
