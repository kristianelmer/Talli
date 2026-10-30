import assert from "node:assert/strict";

export function connectedWebMode(value = process.env.TALLI_CONNECTED_WEB_MODE) {
  if (value === undefined || value === "dev") {
    return { command: "dev", readinessProof: "Ready in", env: {} };
  }
  assert.equal(value, "production", "TALLI_CONNECTED_WEB_MODE must be dev or production");
  // Both Next dev and Next start emit this readiness marker. Building is the
  // caller's responsibility; the fixture only starts the already built app.
  return { command: "start", readinessProof: "Ready in", env: { NODE_ENV: "production" } };
}

export function connectedViewport(value = process.env.TALLI_CONNECTED_VIEWPORT) {
  if (value === undefined || value === "desktop") {
    return { mobile: false, contextOptions: {} };
  }
  assert.equal(value, "mobile", "TALLI_CONNECTED_VIEWPORT must be mobile or desktop");
  return {
    mobile: true,
    contextOptions: {
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    },
  };
}

export async function assertConnectedLayout(page, viewport, checkpoint) {
  if (!viewport.mobile) return;
  const geometry = await page.evaluate(() => ({
    width: window.innerWidth,
    documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
  }));
  const width = page.viewportSize().width;
  // A mobile layout viewport can expand to conceal overflowing content.
  assert.equal(geometry.width, width, `${checkpoint}: layout viewport expanded beyond the configured width`);
  assert.ok(geometry.documentWidth <= width + 1,
    `${checkpoint}: horizontal overflow (${geometry.documentWidth} > ${width})`);
}

export async function activateConnectedButton(page, button, viewport) {
  if (!viewport.mobile) return button.click();
  // Trial tap checks visibility, enabled state, stability and hit targeting
  // without submitting. The following tap uses the actual touch context.
  await button.tap({ trial: true });
  const bounds = await button.boundingBox();
  assert.ok(bounds && bounds.width >= 24 && bounds.height >= 24,
    "connected primary button needs a tap target of at least 24 by 24 CSS pixels");
  await assertConnectedLayout(page, viewport, "before primary action");
  await button.tap();
}

export async function assertConnectedReflow(page, viewport) {
  if (!viewport.mobile) return;
  try {
    await page.setViewportSize({ width: 320, height: 844 });
    await assertConnectedLayout(page, viewport, "populated workspace at 320px");
  } finally {
    await page.setViewportSize(viewport.contextOptions.viewport);
  }
}
