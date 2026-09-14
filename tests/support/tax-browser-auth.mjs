import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

export async function establishOwnerAal2(page, origin) {
  await page.goto(`${origin}/mfa?next=%2Fconnections`);
  await page.getByRole("heading", { name: "Beskytt kontoen før du fortsetter" }).waitFor();
  await page.getByRole("button", { name: "Sett opp autentiseringsapp", exact: true }).click();
  const secret = (await page.locator("code").innerText()).trim();
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret.toUpperCase().replace(/=+$/u, "")].map((character) => {
    const index = alphabet.indexOf(character);
    assert.notEqual(index, -1);
    return index.toString(2).padStart(5, "0");
  }).join("");
  const key = Buffer.from((bits.match(/.{8}/gu) ?? []).map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const code = String((digest.readUInt32BE(digest.at(-1) & 0x0f) & 0x7fffffff) % 1000000).padStart(6, "0");
  await page.getByLabel("Sekssifret kode").fill(code);
  await page.getByRole("button", { name: "Bekreft og fortsett", exact: true }).click();
  await page.waitForURL((url) => url.pathname !== "/mfa");
}
