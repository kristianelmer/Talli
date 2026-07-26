import assert from "node:assert/strict";
import test from "node:test";

import {
  productionRf1086AdapterEnabled,
  rf1086ProductionEnvironment,
} from "../apps/web/app/lib/rf1086-submission.ts";
import { currentAuthorityAdapterCapabilities } from "../apps/web/app/lib/authority-adapters.ts";

const validEnvironment = {
  TALLI_RF1086_PRODUCTION_ENABLED: "true",
  TALLI_PROD_MASKINPORTEN_CLIENT_ID: "7166e743-978e-4a60-8a2d-0a5c00fe6ad0",
  TALLI_PROD_MASKINPORTEN_KEY_ID: "2d275f93-10a2-4839-993e-b14da2b84ad8",
  TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: "-----BEGIN PRIVATE KEY-----\nZmFrZS1wcm9kdWN0aW9uLWtleQ==\n-----END PRIVATE KEY-----",
  TALLI_PROD_RF1086_SCOPE: "skatteetaten:innrapporteringaksjonaerregisteroppgave",
};

test("production stays disabled by default", () => {
  assert.equal(rf1086ProductionEnvironment({}), null);
  assert.equal(productionRf1086AdapterEnabled({}), false);
  assert.deepEqual(currentAuthorityAdapterCapabilities({}).aksjonaerregisteroppgaven, {
    productionImplemented: true,
    productionEnabled: false,
  });
});

test("returns only strict production configuration when every gate is present", () => {
  assert.deepEqual(rf1086ProductionEnvironment(validEnvironment), {
    environment: "production",
    clientId: validEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
    keyId: validEnvironment.TALLI_PROD_MASKINPORTEN_KEY_ID,
    privateKeyPem: validEnvironment.TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM,
    scope: validEnvironment.TALLI_PROD_RF1086_SCOPE,
  });
  assert.equal(productionRf1086AdapterEnabled(validEnvironment), true);
  assert.equal(currentAuthorityAdapterCapabilities(validEnvironment).aksjonaerregisteroppgaven.productionEnabled, true);
});

test("rejects file paths, test material, wrong scope, partial configuration, and loose flag values", () => {
  for (const environment of [
    { ...validEnvironment, TALLI_RF1086_PRODUCTION_ENABLED: "1" },
    { ...validEnvironment, TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: "/Users/me/talli-test.key" },
    { ...validEnvironment, TALLI_PROD_MASKINPORTEN_CLIENT_ID: "test-client" },
    { ...validEnvironment, TALLI_PROD_RF1086_SCOPE: "another:scope" },
    { ...validEnvironment, TALLI_PROD_MASKINPORTEN_KEY_ID: "" },
  ]) {
    assert.throws(() => rf1086ProductionEnvironment(environment), /production|PEM|credential|scope|required/i);
    assert.equal(productionRf1086AdapterEnabled(environment), false);
  }
});
