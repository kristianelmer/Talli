import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { checkOfficialSources, readOfficialSource } from '../scripts/check-rf1086-official-sources.mjs';

const bytes = Buffer.from('<schema/>');
const sha256 = createHash('sha256').update(bytes).digest('hex');
const manifest = { schemaVersion: 1, revision: 'a'.repeat(40), sources: [{
  path: 'static/download/form.xsd', localPaths: ['docs/form.xsd', 'runtime/form.xsd'], sha256,
}] };

test('checks every bundled copy, immutable provenance and current upstream', async () => {
  const local = [], remote = [];
  const result = await checkOfficialSources(manifest, { current: true,
    readLocal: async (path) => { local.push(path); return bytes; },
    readRemote: async (url) => { remote.push(url); return bytes; },
  });
  assert.equal(local.length, 2);
  assert.equal(remote.length, 2);
  assert.ok(remote[0].includes(manifest.revision));
  assert.ok(remote[1].includes('/main/'));
  assert.equal(result[0].currentChecked, true);
});

test('offline checks never claim current verification or use network', async () => {
  const result = await checkOfficialSources(manifest, { readLocal: async () => bytes,
    readRemote: async () => assert.fail('network'),
  });
  assert.equal(result[0].currentChecked, false);
});

test('a changed runtime copy fails before remote reads', async () => {
  await assert.rejects(checkOfficialSources(manifest, { current: true,
    readLocal: async (path) => path.endsWith('runtime/form.xsd') ? Buffer.from('drift') : bytes,
    readRemote: async () => assert.fail('network'),
  }), /RF1086_BUNDLED_SOURCE_DRIFT/);
});

for (const target of ['pinned', 'current']) {
  test(`rejects ${target} source drift without rewriting the pin`, async () => {
    const original = JSON.stringify(manifest);
    await assert.rejects(checkOfficialSources(manifest, { current: true, readLocal: async () => bytes,
      readRemote: async (url) => url.includes(target === 'pinned' ? manifest.revision : '/main/')
        ? Buffer.from('changed') : bytes,
    }), /RF1086_OFFICIAL_SOURCE_DRIFT/);
    assert.equal(JSON.stringify(manifest), original);
  });
}

test('unavailable upstream is a failed gate', async () => {
  await assert.rejects(checkOfficialSources(manifest, { current: true, readLocal: async () => bytes,
    readRemote: async () => { throw new Error('RF1086_SOURCE_UNAVAILABLE'); },
  }), /RF1086_SOURCE_UNAVAILABLE/);
});

test('labelled official examples are pinned independently from allowed-code schemas', async () => {
  const pin = { ...manifest, codeEvidence: [{
    url: 'https://www.skatteetaten.no/contentassets/' + 'a'.repeat(32) + '/example.txt', sha256,
  }] };
  await assert.rejects(checkOfficialSources(pin, { current: true, readLocal: async () => bytes,
    readRemote: async (url) => url.startsWith('https://www.skatteetaten.no') ? Buffer.from('changed') : bytes,
  }), /RF1086_OFFICIAL_CODE_EVIDENCE_DRIFT/);
});

test('official downloads bound bytes, disallow redirects and set a deadline', async () => {
  const url = 'https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/static/download/form.xsd';
  assert.deepEqual(await readOfficialSource(url, async (_, options) => {
    assert.equal(options.redirect, 'error');
    assert.ok(options.signal instanceof AbortSignal);
    return new Response(bytes);
  }), bytes);
  await assert.rejects(readOfficialSource(url, async () => new Response('')), /RF1086_SOURCE_EMPTY/);
  await assert.rejects(readOfficialSource(url, async () => new Response('unavailable', { status: 503 })), /RF1086_SOURCE_UNAVAILABLE/);
  await assert.rejects(readOfficialSource(url, async () => new Response(Buffer.alloc(1024 * 1024 + 1))), /RF1086_SOURCE_TOO_LARGE/);
  await assert.rejects(readOfficialSource('https://example.com/form.xsd', async () => assert.fail()), /RF1086_SOURCE_URL_INVALID/);
});

test('malformed pins and path traversal fail closed', async () => {
  await assert.rejects(checkOfficialSources({ ...manifest, revision: 'main' }), /RF1086_SOURCE_MANIFEST_INVALID/);
  await assert.rejects(checkOfficialSources({ ...manifest, sources: [] }), /RF1086_SOURCE_MANIFEST_INVALID/);
  await assert.rejects(checkOfficialSources({ ...manifest, sources: [{ ...manifest.sources[0], localPaths: ['../outside'] }] }), /RF1086_SOURCE_PATH_INVALID/);
});
