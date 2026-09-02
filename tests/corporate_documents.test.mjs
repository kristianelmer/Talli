import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { PassThrough } from "node:stream";
import test from "node:test";

import {
  MAX_CORPORATE_RENDER_STDERR_BYTES,
  MAX_CORPORATE_RENDER_STDOUT_BYTES,
  canonicalDecisionJson,
  corporateDecisionHash,
  parseCorporateRenderResult,
  renderCorporateDocuments,
} from "../apps/web/app/lib/corporate-documents.ts";

const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/corporate_documents/owner_dividend.json", import.meta.url), "utf8"),
);

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

function rendererPayload(input = fixture) {
  const decisionHash = corporateDecisionHash(input);
  const artifacts = [
    ["dividend_board_proposal", "styrets-forslag-til-utbytte.pdf", Buffer.from("%PDF-1.4\nboard\n")],
    [
      "dividend_general_meeting_minutes",
      "generalforsamlingsprotokoll-utbytte.pdf",
      Buffer.from("%PDF-1.4\ngeneral meeting\n"),
    ],
  ].map(([artifactKind, filename, bytes]) => ({
    artifactKind,
    filename,
    templateVersion: input.template_version,
    decisionHash,
    contentSha256: sha256(bytes),
    byteLength: bytes.length,
    pdfBase64: bytes.toString("base64"),
  }));
  return { status: "rendered", decisionHash, artifacts };
}

test("canonical Node JSON and hash match the Python renderer", async () => {
  assert.equal(canonicalDecisionJson(fixture), JSON.stringify(JSON.parse(canonicalDecisionJson(fixture))));

  const rendered = await renderCorporateDocuments(fixture);
  assert.equal(rendered.status, "rendered");
  assert.equal(rendered.decisionHash, corporateDecisionHash(fixture));
  assert.deepEqual(
    rendered.artifacts.map((artifact) => artifact.artifactKind),
    ["dividend_board_proposal", "dividend_general_meeting_minutes"],
  );
  for (const artifact of rendered.artifacts) {
    assert.equal(artifact.decisionHash, corporateDecisionHash(fixture));
    assert.equal(artifact.byteLength, artifact.pdfBytes.byteLength);
    assert.equal(artifact.contentSha256, sha256(artifact.pdfBytes));
    assert.equal(Buffer.from(artifact.pdfBytes).subarray(0, 5).toString("ascii"), "%PDF-");
  }
});

test("parser independently validates JSON, hashes, lengths, PDF bytes, and exact kinds", () => {
  const parsed = parseCorporateRenderResult(JSON.stringify(rendererPayload()), fixture);
  assert.equal(parsed.status, "rendered");
  assert.equal(parsed.artifacts.length, 2);

  assert.throws(() => parseCorporateRenderResult("not-json", fixture), /valid JSON/i);
  assert.throws(
    () => parseCorporateRenderResult("x".repeat(MAX_CORPORATE_RENDER_STDOUT_BYTES + 1), fixture),
    /output limit/i,
  );

  const wrongHash = rendererPayload();
  wrongHash.artifacts[0].contentSha256 = "0".repeat(64);
  assert.throws(() => parseCorporateRenderResult(JSON.stringify(wrongHash), fixture), /content hash/i);

  const wrongLength = rendererPayload();
  wrongLength.artifacts[0].byteLength += 1;
  assert.throws(() => parseCorporateRenderResult(JSON.stringify(wrongLength), fixture), /byte length/i);

  const invalidBase64 = rendererPayload();
  invalidBase64.artifacts[0].pdfBase64 = "%%%";
  assert.throws(() => parseCorporateRenderResult(JSON.stringify(invalidBase64), fixture), /base64/i);

  const notPdf = rendererPayload();
  const html = Buffer.from("<html>not a pdf</html>");
  notPdf.artifacts[0].pdfBase64 = html.toString("base64");
  notPdf.artifacts[0].byteLength = html.length;
  notPdf.artifacts[0].contentSha256 = sha256(html);
  assert.throws(() => parseCorporateRenderResult(JSON.stringify(notPdf), fixture), /PDF signature/i);

  const missingKind = rendererPayload();
  missingKind.artifacts.pop();
  assert.throws(() => parseCorporateRenderResult(JSON.stringify(missingKind), fixture), /artifact kinds/i);
});

test("parser preserves a narrow blocked result without trusting arbitrary fields", () => {
  assert.deepEqual(
    parseCorporateRenderResult(
      JSON.stringify({
        status: "blocked",
        issues: [{ code: "corporate_documents_non_unanimous", message: "Beslutningen er blokkert." }],
      }),
      fixture,
    ),
    {
      status: "blocked",
      issues: [{ code: "corporate_documents_non_unanimous", message: "Beslutningen er blokkert." }],
    },
  );
  assert.throws(
    () => parseCorporateRenderResult(JSON.stringify({ status: "blocked", issues: [] }), fixture),
    /blocked result/i,
  );
});

class FakeChild extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  stdin = new PassThrough();
  killed = false;

  kill() {
    this.killed = true;
    queueMicrotask(() => this.emit("close", null, "SIGKILL"));
    return true;
  }
}

test("renderer kills subprocesses that exceed bounded stdout or stderr", async () => {
  for (const [stream, limit] of [
    ["stdout", MAX_CORPORATE_RENDER_STDOUT_BYTES],
    ["stderr", MAX_CORPORATE_RENDER_STDERR_BYTES],
  ]) {
    const child = new FakeChild();
    const promise = renderCorporateDocuments(fixture, {
      spawnProcess: () => {
        queueMicrotask(() => child[stream].write(Buffer.alloc(limit + 1)));
        return child;
      },
    });
    await assert.rejects(promise, /output limit/i);
    assert.equal(child.killed, true);
  }
});

test("renderer uses no shell, a fixed argv, a timeout, and a restricted environment", async () => {
  const child = new FakeChild();
  let invocation;
  const resultPromise = renderCorporateDocuments(fixture, {
    pythonBinary: "/synthetic/python",
    env: {
      PATH: "/usr/bin",
      NODE_ENV: "test",
      SUPABASE_SERVICE_ROLE_KEY: "must-not-leak",
      AWS_SECRET_ACCESS_KEY: "must-not-leak",
    },
    spawnProcess: (binary, args, options) => {
      invocation = { binary, args, options };
      queueMicrotask(() => {
        child.stdout.write(JSON.stringify(rendererPayload()));
        child.stdout.end();
        child.stderr.end();
        child.emit("close", 0, null);
      });
      return child;
    },
  });
  const result = await resultPromise;
  assert.equal(result.status, "rendered");
  assert.equal(invocation.binary, "/synthetic/python");
  assert.deepEqual(invocation.args, [
    "-m",
    "holding_cli.main",
    "render-corporate-documents",
    "--stdin-json",
  ]);
  assert.equal(invocation.options.shell, false);
  assert.equal(invocation.options.env.PATH, "/usr/bin");
  assert.equal(invocation.options.env.NODE_ENV, "test");
  assert.equal(invocation.options.env.SUPABASE_SERVICE_ROLE_KEY, undefined);
  assert.equal(invocation.options.env.AWS_SECRET_ACCESS_KEY, undefined);

  const hangingChild = new FakeChild();
  await assert.rejects(
    renderCorporateDocuments(fixture, {
      pythonBinary: "/synthetic/python",
      timeoutMs: 5,
      spawnProcess: () => hangingChild,
    }),
    /timed out/i,
  );
  assert.equal(hangingChild.killed, true);
});

test("corporate rendering owns bytes and facts but delegates object identity to documents", () => {
  const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
  assert.match(actions, /documentType: "corporate_document"/u);
  assert.match(actions, /linkedTo: `corporate_decision:/u);
  assert.match(actions, /uploadDocumentObject/u);
  assert.doesNotMatch(actions, /corporateArtifactStorageKey|uploadCorporateArtifacts/u);
});
