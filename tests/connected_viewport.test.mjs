import assert from "node:assert/strict";
import test from "node:test";
import {
  connectedWebMode,
  connectedViewport,
  assertConnectedLayout,
  activateConnectedButton,
  assertConnectedReflow,
} from "./support/connected-viewport.mjs";

// Pure helper contracts only. These controls never launch Playwright or a DB.
test("web mode defaults to dev and production selects start without a build command", () => {
  const previous = process.env.TALLI_CONNECTED_WEB_MODE;
  try {
    delete process.env.TALLI_CONNECTED_WEB_MODE;
    assert.deepEqual(connectedWebMode(), { command: "dev", readinessProof: "Ready in", env: {} });
    process.env.TALLI_CONNECTED_WEB_MODE = "production";
    assert.deepEqual(connectedWebMode(), {
      command: "start", readinessProof: "Ready in", env: { NODE_ENV: "production" },
    });
  } finally {
    if (previous === undefined) delete process.env.TALLI_CONNECTED_WEB_MODE;
    else process.env.TALLI_CONNECTED_WEB_MODE = previous;
  }
  assert.deepEqual(connectedWebMode("dev"), { command: "dev", readinessProof: "Ready in", env: {} });
  for (const value of ["", "Production", " production", "dev ", "start", "build", null, true]) {
    assert.throws(() => connectedWebMode(value), /must be dev or production/u);
  }
});

test("viewport defaults to the unchanged desktop options and rejects unknown selectors", () => {
  const previous = process.env.TALLI_CONNECTED_VIEWPORT;
  try {
    delete process.env.TALLI_CONNECTED_VIEWPORT;
    assert.deepEqual(connectedViewport(), { mobile: false, contextOptions: {} });
    process.env.TALLI_CONNECTED_VIEWPORT = "mobile";
    assert.equal(connectedViewport().mobile, true);
  } finally {
    if (previous === undefined) delete process.env.TALLI_CONNECTED_VIEWPORT;
    else process.env.TALLI_CONNECTED_VIEWPORT = previous;
  }
  assert.deepEqual(connectedViewport("desktop").contextOptions, {});
  for (const value of ["", "Mobile", " mobile", "desktop ", "tablet", null, true, 390]) {
    assert.throws(() => connectedViewport(value), /must be mobile or desktop/u);
  }
});

test("mobile context is narrow and touch-enabled without sharing mutable option objects", () => {
  const first = connectedViewport("mobile");
  assert.deepEqual(first.contextOptions, {
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  first.contextOptions.viewport.width = 999;
  assert.equal(connectedViewport("mobile").contextOptions.viewport.width, 390);
});

test("desktop helpers perform only the original click, without geometry or reflow work", async () => {
  const viewport = connectedViewport("desktop");
  let clicks = 0;
  await assertConnectedLayout(null, viewport, "desktop");
  await assertConnectedReflow(null, viewport);
  await activateConnectedButton(null, { click: async () => { clicks += 1; } }, viewport);
  assert.equal(clicks, 1);
});

function geometryPage(width = 390, documentWidth = width, innerWidth = width) {
  return {
    viewportSize: () => ({ width, height: 844 }),
    evaluate: async () => ({ width: innerWidth, documentWidth }),
  };
}

test("layout rejects overflow and an expanded mobile viewport that would hide overflow", async () => {
  const mobile = connectedViewport("mobile");
  await assertConnectedLayout(geometryPage(), mobile, "fits");
  await assert.rejects(assertConnectedLayout(geometryPage(390, 420), mobile, "wide"), /horizontal overflow/u);
  await assert.rejects(assertConnectedLayout(geometryPage(390, 980, 980), mobile, "expanded"), /layout viewport expanded/u);
});

test("mobile action checks the target before one real tap; small or blocked targets cannot submit", async () => {
  const mobile = connectedViewport("mobile");
  const taps = [];
  const button = {
    tap: async (options) => { taps.push(options); },
    boundingBox: async () => ({ width: 44, height: 44 }),
  };
  await activateConnectedButton(geometryPage(), button, mobile);
  assert.deepEqual(taps, [{ trial: true }, undefined]);
  taps.length = 0;
  button.boundingBox = async () => ({ width: 23, height: 44 });
  await assert.rejects(activateConnectedButton(geometryPage(), button, mobile), /tap target/u);
  assert.deepEqual(taps, [{ trial: true }]);
  let boundsRead = false;
  button.tap = async () => { throw new Error("blocked target"); };
  button.boundingBox = async () => { boundsRead = true; };
  await assert.rejects(activateConnectedButton(geometryPage(), button, mobile), /blocked target/u);
  assert.equal(boundsRead, false);
});

test("an overflowing mobile page cannot submit an otherwise actionable target", async () => {
  const taps = [];
  await assert.rejects(activateConnectedButton(geometryPage(390, 500), {
    tap: async (options) => { taps.push(options); },
    boundingBox: async () => ({ width: 44, height: 44 }),
  }, connectedViewport("mobile")), /horizontal overflow/u);
  assert.deepEqual(taps, [{ trial: true }]);
});

test("320px reflow restores 390px even when the check fails", async () => {
  for (const overflow of [false, true]) {
    let width = 390;
    const visits = [];
    const page = {
      viewportSize: () => ({ width, height: 844 }),
      evaluate: async () => ({ width, documentWidth: overflow ? width + 50 : width }),
      setViewportSize: async (size) => { width = size.width; visits.push(size); },
    };
    const check = assertConnectedReflow(page, connectedViewport("mobile"));
    if (overflow) await assert.rejects(check, /horizontal overflow/u);
    else await check;
    assert.deepEqual(visits, [{ width: 320, height: 844 }, { width: 390, height: 844 }]);
  }
});
