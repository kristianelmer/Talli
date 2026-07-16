import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

const browserSource = readFileSync(
  new URL("./browser_system_user_flow.mjs", import.meta.url),
  "utf8",
);

test("browser contexts use a catch-all fail-closed egress guard", async () => {
  const { installBrowserEgressGuard } = await import(
    "./fixtures/system-user-authority-mock.mjs"
  );
  assert.equal(typeof installBrowserEgressGuard, "function");

  const owner = fakeContext();
  const ownerViolations = [];
  await installBrowserEgressGuard(owner.context, {
    approvalEnabled: true,
    blockedRequests: ownerViolations,
    mockBaseUrl: "http://127.0.0.1:49152",
  });
  assert.equal(owner.pattern, "**/*");

  const localRoute = fakeRoute({ method: "GET", url: "http://localhost:3000/login" });
  await owner.handler(localRoute.route);
  assert.equal(localRoute.continued, true);

  const externalRoute = fakeRoute({ method: "GET", url: "https://example.invalid/blocked" });
  await owner.handler(externalRoute.route);
  assert.equal(externalRoute.aborted, true);
  assert.deepEqual(ownerViolations, ["blocked_nonloopback_browser_request"]);

  const approvalId = randomUUID();
  const approvalGet = fakeRoute({
    method: "GET",
    url: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${approvalId}`,
  });
  await owner.handler(approvalGet.route);
  assert.equal(approvalGet.fulfilled, true);
  assert.equal(owner.fetches.at(-1)?.url, `http://127.0.0.1:49152/approval?id=${approvalId}`);

  const approvalPost = fakeRoute({
    contentType: "application/x-www-form-urlencoded",
    method: "POST",
    postData: new URLSearchParams({ id: approvalId }).toString(),
    url: "https://am.ui.altinn.no/accessmanagement/ui/systemuser/approve",
  });
  await owner.handler(approvalPost.route);
  assert.equal(approvalPost.fulfilled, true);
  assert.equal(owner.fetches.at(-1)?.url, "http://127.0.0.1:49152/approval/complete");

  const otherOwner = fakeContext();
  const otherOwnerViolations = [];
  await installBrowserEgressGuard(otherOwner.context, {
    approvalEnabled: false,
    blockedRequests: otherOwnerViolations,
    mockBaseUrl: "http://127.0.0.1:49152",
  });
  const forbiddenApproval = fakeRoute({
    method: "GET",
    url: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${randomUUID()}`,
  });
  await otherOwner.handler(forbiddenApproval.route);
  assert.equal(forbiddenApproval.aborted, true);
  assert.deepEqual(otherOwnerViolations, ["blocked_nonloopback_browser_request"]);

  assert.equal((browserSource.match(/installBrowserEgressGuard\(/gu) ?? []).length, 2);
  assert.doesNotMatch(browserSource, /context\.on\("request"/u);
});

test("signed feedback redirect is inspected before a bounded loopback follow", () => {
  assert.match(
    browserSource,
    /const appDownload = await ownerContext\.request\.get\([\s\S]+?maxRedirects: 0[\s\S]+?const signedLocation[\s\S]+?LOOPBACK_HOSTS\.has\(signedUrl\.hostname\)[\s\S]+?const signedDownload = await ownerContext\.request\.get\(signedUrl\.href,[\s\S]+?maxRedirects: 0/u,
  );
});

test("current reconciliation UI reaches Godkjent before DB and reload assertions", () => {
  const click = browserSource.indexOf('getByRole("button", { name: "Sjekk status på nytt" }).click()');
  const acceptedUi = browserSource.indexOf(
    'productionSection.getByText("Godkjent", { exact: true }).waitFor()',
    click,
  );
  const database = browserSource.indexOf("await waitForDatabaseState", click);
  const reload = browserSource.indexOf("await ownerPage.reload()", click);
  assert.ok(click >= 0 && click < acceptedUi && acceptedUi < database && database < reload);
});

test("both browser contexts close before final health and egress assertions", () => {
  const ownerClose = browserSource.indexOf("await ownerContext.close()");
  const otherClose = browserSource.indexOf("await otherContext.close()");
  const healthGate = browserSource.indexOf("assert.deepEqual(browserProblems, [])");
  assert.ok(ownerClose >= 0 && ownerClose < healthGate);
  assert.ok(otherClose >= 0 && otherClose < healthGate);
});

test("local Supabase stop failures join teardown errors", () => {
  assert.match(
    browserSource,
    /teardownStep\(\(\) => stopLocalSupabase\(\), cleanupErrors\)/u,
  );
  assert.match(
    browserSource,
    /function stopLocalSupabase\(\) \{[\s\S]+?const stopped = supabaseCommand[\s\S]+?stopped\.status !== 0[\s\S]+?local_supabase_stop_failed/u,
  );
});

test("RF-1086 reconciliation controls have responsive overflow and focus coverage", () => {
  assert.match(browserSource, /verifyRf1086ResponsiveViewports\(ownerPage\)/u);
  const helper = browserSource.match(
    /async function verifyRf1086ResponsiveViewports[\s\S]+?\n\}/u,
  )?.[0] ?? "";
  assert.match(helper, /\[320, 1440\]/u);
  assert.match(helper, /scrollWidth/u);
  assert.match(helper, /Sjekk status på nytt/u);
  assert.match(helper, /Last ned tilbakemelding/u);
  assert.match(helper, /document\.activeElement/u);
});

function fakeContext() {
  const state = { fetches: [], handler: null, pattern: null };
  return {
    context: {
      request: {
        async fetch(url, options) {
          state.fetches.push({ url, options });
          return {
            async body() {
              return Buffer.from("local-mock");
            },
            headers() {
              return { "content-type": "text/html" };
            },
            status() {
              return 200;
            },
          };
        },
      },
      async route(pattern, handler) {
        state.pattern = pattern;
        state.handler = handler;
      },
    },
    get fetches() {
      return state.fetches;
    },
    get handler() {
      return state.handler;
    },
    get pattern() {
      return state.pattern;
    },
  };
}

function fakeRoute({ contentType = null, method, postData = null, url }) {
  const state = { aborted: false, continued: false, fulfilled: false };
  return {
    route: {
      async abort() {
        state.aborted = true;
      },
      async continue() {
        state.continued = true;
      },
      async fulfill() {
        state.fulfilled = true;
      },
      request() {
        return {
          async headerValue(name) {
            return name === "content-type" ? contentType : null;
          },
          method() {
            return method;
          },
          postData() {
            return postData;
          },
          postDataBuffer() {
            return postData === null ? null : Buffer.from(postData);
          },
          url() {
            return url;
          },
        };
      },
    },
    get aborted() {
      return state.aborted;
    },
    get continued() {
      return state.continued;
    },
    get fulfilled() {
      return state.fulfilled;
    },
  };
}
