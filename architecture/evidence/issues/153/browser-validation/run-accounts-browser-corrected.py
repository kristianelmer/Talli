from pathlib import Path
import os,subprocess
p=Path(__file__).parent
env={**os.environ,'PATH':'/Users/kristianelmer/.codex/issue-192-private/runtime/node-v24.20.0-darwin-arm64/bin:/opt/homebrew/opt/icu4c@78/bin:'+os.environ['PATH'],'UV_PYTHON':'/Users/kristianelmer/.codex/issue-192-private/runtime/python/cpython-3.12.12-macos-aarch64-none/bin/python3.12','DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock','DOCKER_CONFIG':str(p.parent/'issue152-entry/docker-public-config')}
for k in list(env):
 if k.startswith(('SUPABASE_','NEXT_PUBLIC_SUPABASE_','TALLI_PROD_','TALLI_TEST_MASKINPORTEN')) or k in ('DATABASE_URL','DB_URL','API_URL','ANON_KEY','SERVICE_ROLE_KEY'):del env[k]
with (p/'accounts-browser-focused-corrected.log').open('w') as log:
 r=subprocess.run(['bash',str(p/'run-accounts-browser-focused.sh')],env=env,stdout=log,stderr=subprocess.STDOUT)
print('Focused post-Accounts fixture runtime exit',r.returncode)
raise SystemExit(r.returncode)
