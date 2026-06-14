import assert from "node:assert/strict";
import test from "node:test";

import { assertSupportedBrregIdentity, fetchBrregEntity, mapBrregEntity } from "../app/lib/brreg.ts";

test("maps Brønnøysund entity payload to locked company identity", () => {
  const identity = mapBrregEntity({
    organisasjonsnummer: "314259521",
    navn: "Demo Holding AS",
    organisasjonsform: { kode: "AS", beskrivelse: "Aksjeselskap" },
    forretningsadresse: { adresse: ["Storgata 1"], postnummer: "0155", poststed: "OSLO" },
  });

  assert.deepEqual(identity, {
    orgNumber: "314259521",
    name: "Demo Holding AS",
    entityType: "AS",
    address: "Storgata 1",
    postalCode: "0155",
    city: "OSLO",
    statusText: "aktiv",
    source: "brreg",
  });
});

test("fetchBrregEntity rejects invalid organization numbers before network", async () => {
  await assert.rejects(() => fetchBrregEntity("123", async () => {
    throw new Error("should not fetch");
  }), /9 sifre/);
});

test("fetchBrregEntity maps 404 and fetch failures to user-facing errors", async () => {
  await assert.rejects(
    () =>
      fetchBrregEntity("123456789", async () => ({
        ok: false,
        status: 404,
      })),
    /Fant ikke/,
  );
  await assert.rejects(
    () =>
      fetchBrregEntity("123456789", async () => ({
        ok: false,
        status: 500,
      })),
    /Kunne ikke hente/,
  );
});

test("fetchBrregEntity accepts mocked AS payload", async () => {
  const identity = await fetchBrregEntity("314259521", async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      organisasjonsnummer: "314259521",
      navn: "Demo Holding AS",
      organisasjonsform: { kode: "AS" },
      underAvvikling: true,
    }),
  }));

  assert.equal(identity.entityType, "AS");
  assert.equal(identity.statusText, "under avvikling");
});

test("support boundary rejects non-AS Brønnøysund identity before workspace creation", () => {
  assert.throws(
    () =>
      assertSupportedBrregIdentity({
        orgNumber: "123456789",
        name: "Demo ENK",
        entityType: "ENK",
        address: "",
        postalCode: "",
        city: "",
        statusText: "aktiv",
        source: "brreg",
      }),
    /kun AS/,
  );
});
