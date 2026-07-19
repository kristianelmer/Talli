import assert from "node:assert/strict";
import test from "node:test";

import { resolveTalliPythonBinary } from "../app/lib/python-runtime.ts";

test("uses an explicit configured Python runtime", () => {
  assert.equal(
    resolveTalliPythonBinary({
      env: { TALLI_PYTHON_BIN: "/srv/talli/.venv/bin/python" },
      cwd: "/srv/talli",
      exists: () => false,
    }),
    "/srv/talli/.venv/bin/python",
  );
});

test("finds the project virtualenv for local filing-engine calls", () => {
  const result = resolveTalliPythonBinary({
    env: {},
    cwd: "/workspace/talli",
    exists: (path) => path === "/workspace/talli/.venv/bin/python",
  });

  assert.equal(result, "/workspace/talli/.venv/bin/python");
});

test("fails closed when no dependency-complete Python runtime is configured", () => {
  assert.throws(
    () => resolveTalliPythonBinary({ env: {}, cwd: "/workspace/talli", exists: () => false }),
    /TALLI_PYTHON_BIN/,
  );
});
