import {readFileSync,writeFileSync} from 'node:fs';
import {buildAnnualAccountsPayload} from './apps/web/app/lib/annual-accounts.ts';
import {renderAnnualAccountsXml} from './apps/web/app/lib/annual-accounts-xml.ts';
const c=JSON.parse(readFileSync('./architecture/evidence/issues/153/characterization/legacy-pure-characterization.json'));
const results=[];
for(const depth of [100,600,1200]){const input=structuredClone(c.payloadCases[0].input);let v='ignored';for(let i=0;i<depth;i++)v=[v];input.annualData.ignored=v;try{results.push({depth,status:'ok',fieldCount:buildAnnualAccountsPayload(input).fields.length})}catch(e){results.push({depth,status:e.name})}}
writeFileSync(process.argv[2],JSON.stringify(results,null,2)+'\n');console.log(results);
