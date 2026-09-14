import ast,hashlib,json,subprocess
from pathlib import Path
base='32c701e31ff83016342c47a74ab0951ba3eab05d'
source=subprocess.check_output(['git','show',base+':apps/backend/src/talli_backend/authority_tools/_filing.py'],text=True)
namespace={};exec(compile(source,'predecessor-filing','exec'),{'__file__':str(Path('apps/backend/src/talli_backend/authority_tools/_filing.py').resolve()),'__name__':'predecessor_filing'},namespace)
# Execute just the independent pinned decoder, avoiding unrelated imports/module setup.
import math,re
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='case_income_year')
ns={'math':math,'re':re};exec(compile(ast.Module(body=[node],type_ignores=[]),'pinned-case-year','exec'),ns)
values=[None,False,True,0,-0.0,2025,2025.0,2025.5,-2025,1e20,1e-7,10**400,{}, {'x':2025},'', ' ', '\ufeff2025\u2029','\x1c2025','2025','2025.0','+2025','2.025e3','2025junk','0x7e9','0b11111101001','0o3751','-0x7e9','Infinity','-Infinity','NaN','1e999','9'*400,'２０２５','2_025']
values=values+[[v] for v in values]+[[[v]] for v in values]+[[],[None,None],[2025,0],[[None]],['2025',None],[[[]]]]
rows=[]
for i,value in enumerate(values):
 try:result={'year':ns['case_income_year'](value)}
 except Exception as e:result={'errorType':type(e).__name__,'message':str(e)}
 rows.append({'id':f'year-{i:03}','input':value,'expected':result})
out={'baselineRevision':base,'producerSourceSha256':hashlib.sha256(source.encode()).hexdigest(),'cases':rows}
p=Path('architecture/evidence/issues/152/authority-workflow-ownership');p.mkdir(exist_ok=True);(p/'legacy-case-years.json').write_text(json.dumps(out,indent=2)+'\n');print(len(rows))
