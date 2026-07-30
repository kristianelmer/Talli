import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const rootManifest = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
);
const rootLockfile = JSON.parse(
  readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
);
const webManifest = JSON.parse(
  readFileSync(new URL("../apps/web/package.json", import.meta.url), "utf8"),
);

test("root install models the web workspace and its local API client", () => {
  assert.deepEqual(rootManifest.workspaces, ["apps/web", "packages/*"]);
  assert.equal(rootLockfile.packages["apps/web"]?.name, "talli-web");
  assert.equal(
    rootLockfile.packages["packages/talli-api-client"]?.name,
    "@talli/talli-api-client",
  );
  assert.equal(
    rootLockfile.packages["node_modules/@talli/talli-api-client"]?.link,
    true,
  );
});

test("root and web share exact React and Node type dependencies", () => {
  for (const dependency of ["@types/node", "@types/react", "@types/react-dom"]) {
    assert.equal(
      rootManifest.devDependencies[dependency],
      webManifest.devDependencies[dependency],
      `${dependency} must resolve once for the root workspace install`,
    );
  }
});
