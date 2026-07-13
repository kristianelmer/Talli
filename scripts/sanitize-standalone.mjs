import { readdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const standaloneRoot = path.join(root, ".next", "standalone");

for (const entry of await readdir(standaloneRoot, { withFileTypes: true })) {
  if (entry.isFile() && /^\.env(?:\.|$)/u.test(entry.name)) {
    await rm(path.join(standaloneRoot, entry.name), { force: true });
  }
}
