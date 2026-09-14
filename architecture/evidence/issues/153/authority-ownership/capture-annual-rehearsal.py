import hashlib,json,pathlib,subprocess,sys,types
sys.path.insert(0,str(pathlib.Path.cwd()/'apps/backend/tests'))
from annual_accounts_rehearsal_trace import CASES,trace
raw=subprocess.check_output(['git','show','57df4221:apps/backend/src/talli_backend/authority_tools/annual_accounts_test.py'],text=True)
original='from .annual_accounts_transport import AnnualAccountsAuthorityError, AnnualAccountsTransport, exchange_maskinporten_for_altinn_token'
replacement='from talli_backend.adapters.annual_accounts_authority import AnnualAccountsAuthorityError, AnnualAccountsTransport, exchange_maskinporten_for_altinn_token'
assert raw.count(original)==1
module=types.ModuleType('talli_backend.authority_tools.frozen_annual_trace');module.__package__='talli_backend.authority_tools'
exec(compile(raw.replace(original,replacement),'<frozen-57df4221-annual-accounts>', 'exec'),module.__dict__)
result={'sourceRevision':'57df4221','sourceSha256':hashlib.sha256(raw.encode()).hexdigest(),'exposure':'Only old transport import redirected to relocated same HTTP adapter; original run body unchanged; substituted file/clock/revision/provider seams.','cases':[{'id':case,'trace':trace(module,case,relocated=False)} for case in CASES]}
encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
pathlib.Path(sys.argv[1]).write_text(encoded);print(json.dumps({'cases':len(CASES),'sha256':hashlib.sha256(encoded.encode()).hexdigest()}))
