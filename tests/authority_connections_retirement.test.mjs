import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

async function sources(directory) {
  const files = await readdir(directory, { withFileTypes: true });
  return (await Promise.all(files.map(async (entry) => {
    const path = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
    if (entry.isDirectory()) return sources(path);
    return /\.(?:ts|tsx|mjs)$/u.test(entry.name) ? [{ path, text: await readFile(path, "utf8") }] : [];
  }))).flat();
}

test("Authority Connections retirement leaves no web authority signing, token or credential transport", async () => {
  const files = (await Promise.all(["../apps/web/app/", "../apps/web/features/", "../apps/web/lib/"].map(
    (path) => sources(new URL(path, import.meta.url)),
  ))).flat();
  const forbidden = /TALLI_(?:PROD_)?MASKINPORTEN_(?:PRIVATE_KEY|CLIENT_ID|KEY_ID)|requestMaskinportenToken|createRf1086AuthorityClient|createSystemUserAuthorityClient|exchangeMaskinportenFor(?:AnnualAccounts)?AltinnToken/u;
  assert.deepEqual(files.filter(({ text }) => forbidden.test(text)).map(({ path }) => path.pathname), []);
});

test("the four standalone authority commands execute backend modules and retain their public command names", async () => {
  const { scripts } = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  for (const [command, module] of [["token-smoke", "token_smoke"], ["rf1086-test", "rf1086_test"],
    ["company-tax-test", "company_tax_test"], ["annual-accounts-test", "annual_accounts_test"]]) {
    assert.equal(scripts[`authority:${command}`], `uv run --project apps/backend python -m talli_backend.authority_tools.${module}`);
  }
});

test("authority and RF facades are retired while later filing owners retain their frozen records", async () => {
  const registry = JSON.parse(await readFile(new URL("../architecture/compatibility.json", import.meta.url), "utf8"));
  assert.ok(!registry.records.some(({ capability }) => ["authority_connections", "shareholder_register_filing"].includes(capability)));
  for (const capability of ["company_tax_filing", "annual_accounts_filing"])
    assert.ok(registry.records.some((record) => record.capability === capability && record.scopes.length), capability);
});
