import {writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
if(process.version!=='v24.20.0')throw new Error('Pinned Node required');
const inputs=new Set(['','bad','0','1','12','13','31','32','49','50','99','100','999','2026','2026-02-30','July 14, 2026','Tue, 14 Jul 2026 12:00:00 GMT','random 2026','random2026','2026 random','(ignored)2026','2026(ignored)','2026)','-000000','+000000','+010000-01-01T00:00:00Z','2026-07-14\u0000garbage','2026-07-14\u2028','2026-07-14\u0085']);
for(const year of ['0000','0099','0100','1900','2000','2025','2026','9999','+010000','-000001','+275760','-271821','+999999'])
 for(const month of ['00','01','02','04','12','13'])for(const day of ['00','01','28','29','30','31','32']){
  const date=`${year}-${month}-${day}`;inputs.add(date);inputs.add(date+'T00:00:00Z');
 }
for(const date of ['2026-07-14','2026-7-14','07/14/2026','14 July 2026','01/02/03','2026','Jan 1','1 Jan 50'])
 for(const time of ['', ' 00:00', ' 23:59:59', ' 24:00', ' 24:00:00.001', 'T12:00:00', ' 1::', ' 1:2:3',' 12:34:56.12',' 13:00 pm',' 12:00 am',' 0:00 pm'])
  for(const zone of ['', 'Z',' GMT',' UTC+0200',' +02:00',' -8',' +2500'])inputs.add(date+time+zone);
for(const value of ['2026-07-14T23:59:59.1Z','2026-07-14T23:59:59.1234567890123Z','2026-07-14T24:00Z','2026-07-14T24:00:00.000Z','2026-07-14T24:00:00.0001Z','2026-07-14T12:00+0200','2026-07-14T12:00+02:00','2026-07-14T12:00+2400','2026-07-14T12:00+00:60','2026-07-14t12:00z','+275760-09-13T00:00:00.000Z','+275760-09-13T00:00:00.001Z','-271821-04-20T00:00:00.000Z','-271821-04-19T23:59:59.999Z'])inputs.add(value);
const data={runtime:process.version,v8:process.versions.v8,timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone,scope:'Finite Date.parse acceptance used by existing TT02 evidence import; no provider operation or authority-time claim.',cases:[...inputs].map(input=>({input,valid:Number.isFinite(Date.parse(input))}))};
const raw=JSON.stringify(data,null,2)+'\n';writeFileSync(process.argv[2],raw,{flag:'wx',mode:0o600});console.log(JSON.stringify({cases:data.cases.length,sha256:createHash('sha256').update(raw).digest('hex')}));
