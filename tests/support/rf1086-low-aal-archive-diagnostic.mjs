import assert from "node:assert/strict";
import fs from "node:fs";
import { stat } from "node:fs/promises";
import { join } from "node:path";

const ARCHIVE_PATH = "/filing/aksjonaerregisteroppgaven/source/archive";
const ARCHIVE_ROUTE = "/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route";
const COMPILED_ROUTE = "app/(owner)/filing/aksjonaerregisteroppgaven/source/archive/route.js";
const MANIFEST_LIMIT = 64 * 1024;

// This preserves the original403 assertion. Diagnostics never fetch again or
// read Playwright's whole-body APIs, which cannot provide a bounded prefix.
export async function assertRfArchiveLowAalDenied(response, { root = process.cwd(), observation, deadline = Infinity } = {}) {
  const status = response.status();
  const end = Math.min(deadline, observation?.deadline ?? Infinity, performance.now() + (status === 403 ? 250 : 1_000));
  // Optional collection shares this absolute deadline with the existing file
  // diagnostics; it cannot replace the original status assertion.
  let requestObservation;
  if (observation) {
    try { requestObservation = await observation.finish(response, end); } catch {}
  }
  if (status === 403) return;
  const evidence = {
    responsePathMatches: null, contentType: "unavailable", attachmentHeaderPresent: null,
    bodyInspection: "unavailable", routeManifest: "unavailable", compiledRoute: "unavailable",
  };
  if (requestObservation) evidence.requestObservation = {
    status: requestObservation.status, reason: requestObservation.reason, shape: requestObservation.shape,
  };
  try { evidence.responsePathMatches = new URL(response.url()).pathname === ARCHIVE_PATH; } catch {}
  try {
    const headers = response.headers();
    const type = (headers["content-type"] ?? "").slice(0, 256).split(";")[0].trim().toLowerCase();
    evidence.contentType = type === "text/html" ? "html"
      : ["application/json", "application/problem+json"].includes(type) ? "json"
      : type === "text/plain" ? "text" : "other";
    evidence.attachmentHeaderPresent = Object.hasOwn(headers, "content-disposition");
  } catch {}

  const controller = new AbortController();
  let timer;
  try {
    const server = join(root, "apps/web/.next/dev/server");
    await Promise.race([
      Promise.all([
        inspectManifest(join(server, "app-paths-manifest.json"), controller.signal)
          .then(value => { evidence.routeManifest = value; }),
        stat(join(server, COMPILED_ROUTE)).then(info => {
          evidence.compiledRoute = info.isFile() ? "present" : "unavailable";
        }, error => { evidence.compiledRoute = error.code === "ENOENT" ? "absent" : "unavailable"; }),
      ]),
      new Promise(resolve => { timer = setTimeout(() => { controller.abort(); resolve(); }, Math.max(0, end - performance.now())); }),
    ]);
  } catch {
    // Evidence collection must not replace the original access assertion.
  } finally {
    clearTimeout(timer);
    controller.abort();
  }
  assert.equal(status, 403, `rf_archive_low_aal_failure ${JSON.stringify(evidence)}`);
}

async function inspectManifest(path, signal) {
  let stream;
  try {
    stream = fs.createReadStream(path, { start: 0, end: MANIFEST_LIMIT, highWaterMark: MANIFEST_LIMIT + 1, signal });
    const chunks = [];
    let size = 0;
    for await (const chunk of stream) {
      size += chunk.length;
      if (size > MANIFEST_LIMIT) return "unavailable";
      chunks.push(chunk);
    }
    const manifest = JSON.parse(Buffer.concat(chunks, size).toString("utf8"));
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) return "unavailable";
    if (!Object.hasOwn(manifest, ARCHIVE_ROUTE)) return "absent";
    return manifest[ARCHIVE_ROUTE] === COMPILED_ROUTE ? "present" : "unavailable";
  } catch (error) {
    return error.code === "ENOENT" ? "absent" : "unavailable";
  } finally {
    stream?.destroy();
  }
}
