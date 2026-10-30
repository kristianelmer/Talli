import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { captureFrontendStep } from "./frontend-capture.mjs";

export const narrowAudit = process.env.TALLI_FRONTEND_NARROW_AUDIT === "1";

/** Numeric layout evidence only: no enrollment text, image, URL or value. */
export async function recordMfaGeometry(page) {
  const directory = process.env.TALLI_FRONTEND_CAPTURE_DIR;
  if (!directory) return;
  assert.ok(isAbsolute(directory));
  assert.equal(new URL(page.url()).pathname, "/mfa");
  const geometry = await page.evaluate(() => {
    const bounds = (selector) => {
      const rect = document.querySelector(selector)?.getBoundingClientRect();
      return rect ? { left: rect.left, right: rect.right, width: rect.width, height: rect.height } : null;
    };
    return {
      viewportWidth: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      codeInput: bounds("#ownerMfaCode"),
      qrImage: bounds(".ownerMfaCard img"),
      manualKey: bounds(".ownerMfaCard code"),
    };
  });
  await writeFile(join(directory, "mfa-geometry.json"), JSON.stringify({
    source: process.env.TALLI_FRONTEND_CAPTURE_SOURCE,
    evidence: "numeric layout only; no enrollment secret/QR screenshot",
    geometry,
  }, null, 2), { mode: 0o600 });
}

/** Reach the actual control through browser Tab navigation, never DOM focus. */
export async function tabTo(page, target) {
  await target.waitFor({ state: "visible" });
  for (let count = 0; count < 100; count += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) {
      // Let the browser's native smooth focus scroll settle; never scroll the
      // target into view for it, which would conceal a keyboard defect.
      await target.evaluate(async (element) => {
        const deadline = performance.now() + 1_500;
        let previous = "";
        let stable = 0;
        while (performance.now() < deadline) {
          await new Promise(requestAnimationFrame);
          const rect = element.getBoundingClientRect();
          const position = `${rect.left}:${rect.right}:${rect.top}:${rect.bottom}`;
          stable = position === previous ? stable + 1 : 0;
          previous = position;
          if (stable >= 3 && rect.top >= -1 && rect.bottom <= innerHeight + 1) return;
        }
      });
      const focus = await target.evaluate((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return {
          visible: element.matches(":focus-visible"),
          outline: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0,
          shadow: style.boxShadow !== "none",
          // Native scrolling rounds fractional CSS pixels at viewport edges.
          inViewport: rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1,
          bounds: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: innerWidth, height: innerHeight },
        };
      });
      if (!focus.inViewport && new URL(page.url()).pathname !== "/mfa") {
        await captureFrontendStep(page, "08-keyboard-target-failure");
      }
      assert.equal(focus.visible, true, "keyboard target does not expose focus-visible");
      assert.ok(focus.outline || focus.shadow, "keyboard target has no outline or focus shadow");
      assert.equal(focus.inViewport, true, `keyboard target is clipped or outside the viewport: ${JSON.stringify(focus.bounds)}`);
      return;
    }
    await page.keyboard.press("Tab");
  }
  assert.fail("control is not reachable within100 Tab presses");
}

export async function activate(page, target) {
  if (!narrowAudit) return target.click();
  await tabTo(page, target);
  await page.keyboard.press("Enter");
}

export async function fillField(page, target, value) {
  if (!narrowAudit) return target.fill(value);
  await tabTo(page, target);
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type(value);
}

export async function chooseRadio(page, fieldset, target) {
  const checked = fieldset.locator('input[type="radio"]:checked');
  await tabTo(page, await checked.count() ? checked : fieldset.locator('input[type="radio"]').first());
  for (let count = 0; count < 4; count += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) {
      await page.keyboard.press("Space");
      assert.equal(await target.isChecked(), true);
      return;
    }
    await page.keyboard.press("ArrowRight");
  }
  assert.fail("radio answer is not reachable with arrow keys");
}
