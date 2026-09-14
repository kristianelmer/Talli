import json,sys
from pathlib import Path
from test_annual_accounts_filing import source,payload,capture
from talli_backend.modules.annual_accounts_filing.public import build_annual_accounts
cases=json.loads(Path(sys.argv[1]).read_text());out=[dict(id=c['id'],output=capture(lambda c=c:payload(build_annual_accounts(source(c['input']))))) for c in cases]
Path(sys.argv[2]).write_text(json.dumps(out,indent=2)+'\n')
