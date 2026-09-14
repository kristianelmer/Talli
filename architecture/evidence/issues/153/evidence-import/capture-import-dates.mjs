import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

if (process.version !== 'v24.20.0') throw new Error('Pinned Node required');
const root = process.cwd();
const sourcePath = `${root}/apps/web/app/lib/authority-test-evidence.ts`;
const { buildAnnualAccountsAuthorityTestRunFromEvidence: project } = await import(pathToFileURL(sourcePath));
const base = JSON.parse(readFileSync(`${root}/architecture/evidence/issues/153/characterization/legacy-pure-characterization.json`)).evidenceCases[0].input;
const original = JSON.parse(readFileSync(`${root}/architecture/evidence/issues/153/evidence-import/legacy-date-parse.json`));
function run(input) {
  const request = structuredClone(base);
  request.evidence.submission.processEndedAt = input;
  try { project(request); return { input, valid: true }; }
  catch (error) { return { input, valid: false, error: error.message }; }
}
const cases = original.cases.map(({ input }) => run(input));
const boundaries = [];
for (const zone of ['UTC', 'Europe/Oslo', 'America/New_York', 'Pacific/Kiritimati', 'Pacific/Pago_Pago', 'Asia/Kathmandu']) {
  process.env.TZ = zone;
  const inputs = new Set();
  for (const date of ['-271821-04-19', '-271821-04-20', '-271821-04-21', '+275760-09-12', '+275760-09-13', '+275760-09-14']) {
    for (const hour of ['00', '01', '02', '04', '05', '12', '14', '18', '23', '24']) {
      for (const time of [`${hour}:00:00.000`, `${hour}:00:00.001`, `${hour}:59:59.999`]) {
        for (const suffix of ['', 'Z', '+14:00', '-12:00']) inputs.add(`${date}T${time}${suffix}`);
      }
    }
  }
  boundaries.push({ zone, cases: [...inputs].map(run) });
}
const result = { runtime: process.version, v8: process.versions.v8,
  sourceSha256: createHash('sha256').update(readFileSync(sourcePath)).digest('hex'),
  scope: 'Actual released Accounts importer: evidenceString trim and Date.parse, with explicit recordedAt; no provider operation.',
  cases, boundaries };
const raw = JSON.stringify(result, null, 2) + '\n';
writeFileSync(process.argv[2], raw, { flag: 'wx' });
console.log(JSON.stringify({ cases: cases.length, boundaryCases: boundaries.reduce((n, x) => n + x.cases.length, 0), sha256: createHash('sha256').update(raw).digest('hex') }));
