from pathlib import Path
import subprocess,os,json,uuid,time
base=Path(__file__).resolve().parent
container='talli-accounts-role-probe-'+uuid.uuid4().hex[:12]
env={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock','DOCKER_CONFIG':str(base.parent/'issue152-entry/docker-public-config')}
def docker(args,**kw):return subprocess.run(['docker',*args],env=env,capture_output=True,text=True,**kw)
def sql(statement,check=True):
 r=docker(['exec','-i',container,'psql','-U','postgres','-v','ON_ERROR_STOP=1','-Atq'],input=statement)
 if check:assert r.returncode==0,r.stderr
 return r
(base/'role-creation-owned-container.json').write_text(json.dumps({'container':container,'purpose':'disposable local PG17 CREATEROLE probe'}))
try:
 r=docker(['run','--rm','--detach','--name',container,'--env','POSTGRES_HOST_AUTH_METHOD=trust','postgres:17']);assert r.returncode==0,r.stderr
 for _ in range(80):
  if sql('select 1;',False).returncode==0:break
  time.sleep(.25)
 else:raise AssertionError('owned postgres startup failed')
 sql('create role accounts_creator nologin noinherit nosuperuser createrole;')
 before=sql('select count(*) from pg_auth_members;').stdout.strip()
 result=sql('''set session authorization accounts_creator;
create role accounts_owned nologin noinherit nosuperuser nocreaterole;
select json_build_object('role',r.rolname,'member',u.rolname,'grantor',g.rolname,'admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member join pg_roles g on g.oid=m.grantor where r.rolname='accounts_owned';''')
 automatic=json.loads(result.stdout.strip());assert automatic=={'role':'accounts_owned','member':'accounts_creator','grantor':'postgres','admin':True,'inherit':False,'set':False}
 rejected=sql('set session authorization accounts_creator; revoke accounts_owned from accounts_creator granted by postgres;',False)
 assert rejected.returncode!=0
 retained=json.loads(sql("select json_build_object('admin',admin_option,'inherit',inherit_option,'set',set_option) from pg_auth_members where roleid='accounts_owned'::regrole;").stdout.strip());assert retained=={'admin':True,'inherit':False,'set':False}
 sql('''set session authorization accounts_creator;
grant accounts_owned to accounts_creator with set true granted by accounts_creator;
revoke accounts_owned from accounts_creator granted by accounts_creator;''')
 assert json.loads(sql("select json_build_object('admin',admin_option,'inherit',inherit_option,'set',set_option) from pg_auth_members where roleid='accounts_owned'::regrole;").stdout.strip())==retained
 sql('create role superuser_created nologin noinherit;')
 assert sql("select count(*) from pg_auth_members where roleid='superuser_created'::regrole;").stdout.strip()=='0'
 evidence={'status':'REPRODUCED_EXPECTED_ENGINE_CREATOR_ADMIN_GRANT','postgresVersion':sql('show server_version;').stdout.strip(),'automaticGrant':automatic,'creatorCannotRevokeBootstrapGrant':True,'revokeError':rejected.stderr.strip(),'temporarySelfGrantExactlyRemoved':True,'superuserCreationAddsNoMembership':True,'initialMembershipCount':int(before),'mode':'OWNED_DISPOSABLE_LOCAL_POSTGRES_NO_HOSTED_OR_PROVIDER'}
finally:
 removed=docker(['rm','--force','--volumes',container]);assert removed.returncode==0,removed.stderr
 print(json.dumps({'containerRemoved':True,'volumeRemoved':True,**evidence},indent=2))
