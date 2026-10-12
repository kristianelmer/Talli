import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const maximumBytes = 1024 * 1024;
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');

export async function readOfficialSource(url, fetchSource = fetch) {
  const parsed = new URL(url);
  const official = (parsed.origin === 'https://raw.githubusercontent.com'
      && parsed.pathname.startsWith('/Skatteetaten/api-dokumentasjon/'))
    || (parsed.origin === 'https://www.skatteetaten.no'
      && /^\/contentassets\/[a-f0-9]{32}\/[A-Za-z0-9_.-]+$/.test(parsed.pathname));
  if (!official
      || parsed.search || parsed.hash || parsed.username || parsed.password) {
    throw new Error('RF1086_SOURCE_URL_INVALID');
  }
  const response = await fetchSource(url, { redirect: 'error', signal: AbortSignal.timeout(15000) });
  if (!response.ok || !response.body) throw new Error('RF1086_SOURCE_UNAVAILABLE');
  const chunks = [];
  let length = 0;
  for await (const chunk of response.body) {
    length += chunk.byteLength;
    if (length > maximumBytes) throw new Error('RF1086_SOURCE_TOO_LARGE');
    chunks.push(Buffer.from(chunk));
  }
  if (!length) throw new Error('RF1086_SOURCE_EMPTY');
  return Buffer.concat(chunks);
}

export async function checkOfficialSources(manifest, { current = false, readLocal = readFile,
  readRemote = readOfficialSource, repositoryRoot = root } = {}) {
  if (manifest.schemaVersion !== 1 || !/^[a-f0-9]{40}$/.test(manifest.revision)
      || !Array.isArray(manifest.sources) || !manifest.sources.length) {
    throw new Error('RF1086_SOURCE_MANIFEST_INVALID');
  }
  const results = [];
  for (const source of manifest.sources) {
    if (!/^[a-f0-9]{64}$/.test(source.sha256)
        || !/^static\/download\/[A-Za-z0-9_.-]+$/.test(source.path)
        || !Array.isArray(source.localPaths) || !source.localPaths.length) {
      throw new Error('RF1086_SOURCE_MANIFEST_INVALID');
    }
    for (const localPath of source.localPaths) {
      const path = resolve(repositoryRoot, localPath);
      if (!path.startsWith(resolve(repositoryRoot) + '/')) throw new Error('RF1086_SOURCE_PATH_INVALID');
      if (digest(await readLocal(path)) !== source.sha256) {
        throw new Error(`RF1086_BUNDLED_SOURCE_DRIFT: ${localPath}`);
      }
    }
    if (current) {
      const base = 'https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/';
      // Check both the immutable provenance and today's published bytes. Never
      // update a pin automatically: a source change requires a mapping review.
      for (const revision of [manifest.revision, 'main']) {
        if (digest(await readRemote(base + revision + '/' + source.path)) !== source.sha256) {
          throw new Error(`RF1086_OFFICIAL_SOURCE_DRIFT: ${source.path} (${revision})`);
        }
      }
    }
    results.push({ path: source.path, sha256: source.sha256, currentChecked: current });
  }
  for (const source of manifest.codeEvidence ?? []) {
    if (!/^[a-f0-9]{64}$/.test(source.sha256) || typeof source.url !== 'string') {
      throw new Error('RF1086_SOURCE_MANIFEST_INVALID');
    }
    if (current && digest(await readRemote(source.url)) !== source.sha256) {
      throw new Error('RF1086_OFFICIAL_CODE_EVIDENCE_DRIFT');
    }
    results.push({ url: source.url, sha256: source.sha256, currentChecked: current });
  }
  return results;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.slice(2).some((value) => value !== '--current')) throw new Error('RF1086_SOURCE_ARGUMENT_INVALID');
    const manifest = JSON.parse(await readFile(resolve(root, 'docs/filing/rf1086-official-sources.json'), 'utf8'));
    const sources = await checkOfficialSources(manifest, { current: process.argv.includes('--current') });
    process.stdout.write(JSON.stringify({ status: 'PASS', sources }) + '\n');
  } catch (error) {
    const message = String(error?.message ?? '');
    process.stderr.write((message.startsWith('RF1086_') ? message : 'RF1086_SOURCE_CHECK_FAILED') + '\n');
    process.exitCode = 1;
  }
}
