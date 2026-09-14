"""Additional read-only verification of the #153 complete-gate runtime extent."""
from pathlib import Path
import hashlib,json,subprocess,sys
revision=sys.argv[1]
gate_path=Path('architecture/evidence/customer-ready-gates')/(revision+'.json')
gate=json.loads(gate_path.read_text())
transcript=Path(gate['transcriptPath']).read_text()
assert gate['revision']==revision and gate['verdict']=='pass'
assert len(gate['checks'])==11 and all(x['exitCode']==0 for x in gate['checks'])
assert 'sha256:'+hashlib.sha256(transcript.encode()).hexdigest()==gate['transcriptDigest']
phases=['test:supabase-predecessor','test:supabase-rf-workspace','test:browser-owner',
        'test:ledger-hosted-migration-authority','test:corporate-governance-database-lifecycle',
        'test:billing-database-lifecycle','test:authority-connections-database','test:company-tax-database',
        'test:annual-accounts-database','test:browser-owner-annual','test:supabase-rf-feedback',
        'test:browser-authority-connections','test:browser-shareholder-register-filing',
        'test:browser-company-tax','test:browser-annual-accounts']
positions=[]
for phase in phases:
    marker='> talli-repository@0.1.0 '+phase+'\n'
    assert transcript.count(marker)==1,(phase,transcript.count(marker))
    positions.append(transcript.index(marker))
assert positions==sorted(positions)
assert '✔ Accounts owner imports pending evidence, records controls and reads scoped source history' in transcript
accounts_section=transcript[positions[8]:positions[9]]
assert '41 passed' in accounts_section
assert 'test:supabase-advisors' in accounts_section
assert 'fail 0' in transcript[positions[-1]:]
assert '[database-isolation] exit=0\n' in transcript
source_paths=['scripts/test-supabase-local.sh','scripts/rehearse-accounts-topology.mjs',
              'tests/browser_annual_accounts_filing.mjs','apps/backend/tests/test_annual_accounts_filing_lifecycle.py']
print(json.dumps({'status':'PASS_ADDITIONAL_ACCOUNTS_RUNTIME_EXTENT_VERIFICATION',
    'revision':revision,'transcriptDigest':gate['transcriptDigest'],'orderedMandatoryPhases':phases,
    'accountsSqlCases':41,'accountsBrowser':'REAL_OWNER_LOGIN_TOTP_HTTP_RESTRICTED_SQL_PASS',
    'finalAccountsAdvisors':'EXECUTED_BETWEEN_ACCOUNTS_ACTIVATION_AND_FINAL_OWNER_LANES',
    'sourceBindings':{p:hashlib.sha256(subprocess.check_output(['git','show',revision+':'+p])).hexdigest() for p in source_paths},
    'limits':['Synthetic retained test evidence and no provider egress; no genuine authority or production filing claim.']},indent=2))
