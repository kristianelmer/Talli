import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

/** Optional evidence from an existing real browser fixture; never live data. */
export async function captureFrontendStep(page, name) {
  const directory = process.env.TALLI_FRONTEND_CAPTURE_DIR;
  if (!directory) return;
  assert.ok(isAbsolute(directory), "frontend capture requires an explicit absolute directory");
  assert.match(name, /^[a-z0-9-]+$/u);
  const url = new URL(page.url());
  assert.equal(url.protocol, "http:");
  assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(url.hostname));
  if (url.pathname === "/mfa") {
    assert.equal(await page.locator("#ownerMfaScanHeading, .ownerMfaCard code, .ownerMfaCard img").count(), 0,
      "never capture enrollment keys or QR codes");
    const code = page.locator("#ownerMfaCode");
    assert.ok(!(await code.count()) || !(await code.inputValue()), "never capture a typed authentication code");
  }
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const original = page.viewportSize();
  const observations = [];
  try {
    const sizes = [
      ["mobile", { width: 390, height: 844 }],
      ["desktop", { width: 1440, height: 1000 }],
    ];
    if (process.env.TALLI_FRONTEND_NARROW_AUDIT === "1") {
      sizes.unshift(["narrow", { width: 320, height: 844 }]);
    }
    for (const [size, viewport] of sizes) {
      await page.setViewportSize(viewport);
      const filename = `${name}-${size}.jpg`;
      const bytes = await page.screenshot({ type: "jpeg", fullPage: false });
      await writeFile(join(directory, filename), bytes, { mode: 0o600 });
      observations.push({
        filename, viewport, pathname: url.pathname,
        horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
        ...(process.env.TALLI_FRONTEND_NARROW_AUDIT === "1" ? {
          accessibility: await page.evaluate(() => {
            const active = document.activeElement;
            const style = active ? getComputedStyle(active) : null;
            return {
              activeTag: active?.tagName,
              activeName: active?.getAttribute("aria-label") || Array.from(active?.labels || []).map((label) => label.textContent.trim()).join(" ") || (active?.matches("button,h1,h2,legend,a") ? active.textContent.trim() : ""),
              focusVisible: active?.matches(":focus-visible"),
              outline: style?.outline,
              boxShadow: style?.boxShadow,
              alertCount: document.querySelectorAll('main [role="alert"]').length,
            };
          }),
        } : {}),
      });
    }
  } finally {
    if (original) await page.setViewportSize(original);
  }
  await writeFile(join(directory, `${name}.json`), JSON.stringify({
    evidence: "canonical local browser fixture; synthetic identities/provider data; no hosted proof",
    source: process.env.TALLI_FRONTEND_CAPTURE_SOURCE || "unrecorded",
    observations,
  }, null, 2), { mode: 0o600 });
}
