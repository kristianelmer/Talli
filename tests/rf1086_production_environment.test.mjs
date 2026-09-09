import assert from "node:assert/strict";
import test from "node:test";
import { currentAuthorityAdapterCapabilities } from "../apps/web/app/lib/authority-adapters.ts";

test("legacy web default cannot infer backend production readiness from browser-host environment", () => {
  for (const environment of [{}, { TALLI_RF1086_PRODUCTION_ENABLED: "true" }]) {
    assert.deepEqual(currentAuthorityAdapterCapabilities(environment).aksjonaerregisteroppgaven, {
      productionImplemented: true, productionEnabled: false,
    });
  }
});
