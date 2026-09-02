import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("..", import.meta.url);

test("full-launch source configuration is exact off and public contracts expose no pilot authority", async () => {
  const [environment, openapi, main, migration, webServer] = await Promise.all([
    readFile(new URL(".env.example", root), "utf8"),
    readFile(new URL("contracts/openapi/talli-v1.json", root), "utf8"),
    readFile(new URL("apps/backend/src/talli_backend/main.py", root), "utf8"),
    readFile(
      new URL(
        "supabase/migrations/20260829074916_validation_observation_authority.sql",
        root,
      ),
      "utf8",
    ),
    readFile(
      new URL("apps/web/features/public-acquisition/server.ts", root),
      "utf8",
    ),
  ]);

  assert.match(environment, /^TALLI_PRODUCT_MODE=full-launch$/mu);
  assert.match(environment, /^TALLI_VALIDATION_OBSERVATION_MODE=off$/mu);
  assert.doesNotMatch(
    openapi,
    /validationObservationMode|validationRunId|pilotEntitlementId|validationCaseCode/u,
  );
  assert.match(main, /TALLI_VALIDATION_OBSERVATION_MODE/u);
  assert.match(main, /TALLI_PRODUCT_MODE/u);
  assert.match(migration, /values \(true, 'off'\)/u);
  assert.match(migration, /ready_for_full_launch/u);
  assert.doesNotMatch(migration, /values\s*\(\s*'V2P8-/u);
  assert.doesNotMatch(migration, /values\s*\([^)]*'V-(?:0[1-9]|1[0-2])'/u);
  assert.doesNotMatch(webServer, /validation[_-]observation|pilotEntitlement|approvedRun/u);
});
