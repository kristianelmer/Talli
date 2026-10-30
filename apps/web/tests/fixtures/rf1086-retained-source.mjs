import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// Genuine Documents-first V2 source + V3 approval, projected by the actual V6
// backend route. Pure TestClient/owner codecs only: no SQL, Auth or blob service.
export function retainedArchiveSource() {
  const root = fileURLToPath(new URL("../../../../", import.meta.url));
  const python = process.env.TALLI_BACKEND_PYTHON_BIN ?? process.env.TALLI_PYTHON_BIN
    ?? root + "apps/backend/.venv/bin/python";
  const value = JSON.parse(execFileSync(python, ["-B", "-c", `
import json
from test_rf1086_retained_archive_source_api import client,params,HEADERS,ROUTE,OLD_ROUTE
from rf1086_retained_stream_fixture import retained_stream_fixture
archive, originals = retained_stream_fixture(amendments=1,status='accepted',legacy=True,independent=True)
http, _, _ = client(archive, originals)
current = http.get(ROUTE,params=params(archive),headers=HEADERS)
assert current.status_code == 200
print(json.dumps({'body':current.json(),'oldStatus':http.get(OLD_ROUTE,params=params(archive),headers=HEADERS).status_code}))
`], { cwd: root, encoding: "utf8", timeout: 30_000, maxBuffer: 16 * 1024 * 1024,
    env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: "1",
      PYTHONPATH: root + "apps/backend/src:" + root + "apps/backend/tests" } }));
  assert.equal(value.oldStatus, 503);
  return value.body;
}
