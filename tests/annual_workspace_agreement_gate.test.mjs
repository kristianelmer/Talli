import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("direct annual workspace routes preserve the current agreement gate", async () => {
  const source = await readFile(
    new URL("../apps/web/app/lib/annual-workspace-server.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /listCustomerAgreementAcceptances/u);
  assert.match(source, /companiesRequiringCurrentCustomerAgreement/u);
  assert.match(
    source,
    /membership\.role\s*===\s*"owner"\s*\?\s*"\/dashboard"\s*:\s*"\/dashboard\?agreement=required"/u,
  );
});

test("non-owners get a stable fail-closed agreement message instead of a redirect loop", async () => {
  const dashboard = await readFile(
    new URL("../apps/web/app/(owner)/dashboard/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(dashboard, /params\?\.agreement\s*===\s*"required"/u);
  assert.match(dashboard, /Avtalen må godkjennes av en eier/u);
  assert.match(dashboard, /redirect\(annualOverviewHref\(/u);
});
