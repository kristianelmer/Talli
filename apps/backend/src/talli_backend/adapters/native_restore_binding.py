"""Finite native backup/target comparison for the owned offline recovery adapter."""
import json
import re
from hashlib import sha256

from psycopg import sql

ROLE_SQL="""
select coalesce(jsonb_agg(to_jsonb(r)-'oid' order by r.rolname),'[]'::jsonb)
from pg_authid r;
select coalesce(jsonb_agg(jsonb_build_array(r.rolname,m.rolname,g.rolname,a.admin_option,a.inherit_option,a.set_option)
order by r.rolname,m.rolname,g.rolname),'[]'::jsonb)
from pg_auth_members a join pg_roles r on r.oid=a.roleid join pg_roles m on m.oid=a.member
join pg_roles g on g.oid=a.grantor;
"""
ATTRIBUTES=r"""
const fs=require('fs'),path=require('path'),xattr=require('fs-xattr'),entries=[];
function walk(relative){const file=path.join('/mnt',relative),stat=fs.lstatSync(file);
if(stat.isSymbolicLink()||(!stat.isDirectory()&&!stat.isFile()))throw Error('unsupported storage file');
const attributes={};for(const key of xattr.listSync(file).sort())attributes[key]=xattr.getSync(file,key).toString('base64');
entries.push({path:relative,directory:stat.isDirectory(),attributes});
if(stat.isDirectory())for(const name of fs.readdirSync(file).sort())walk(path.join(relative,name));}
walk('.');process.stdout.write(JSON.stringify(entries));
"""

GUARDS_SQL="""
set search_path='';
select jsonb_build_object(
 'functions',(select coalesce(jsonb_agg(jsonb_build_object(
   'signature',p.oid::regprocedure::text,'definition',pg_get_functiondef(p.oid),'owner',pg_get_userbyid(p.proowner),
   'acl',(select coalesce(jsonb_agg(a.item order by a.item::text),'[]') from
      (select jsonb_build_array(pg_get_userbyid(x.grantor),case when x.grantee=0 then 'PUBLIC' else pg_get_userbyid(x.grantee) end,x.privilege_type,x.is_grantable) item
       from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) x) a)) order by p.oid::regprocedure::text),'[]')
   from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='documents'
   and p.proname in ('local_native_disposition_state_v1','local_native_disposition_prepare_v1',
     'local_native_disposition_storage_retired_v1','local_native_disposition_delete_allowed_v1',
     'local_native_disposition_finalize_v1','local_native_disposition_row_guard_v1')),
 'triggers',(select coalesce(jsonb_agg(jsonb_build_object('table',t.tgrelid::regclass::text,
     'name',t.tgname,'enabled',t.tgenabled,'definition',pg_get_triggerdef(t.oid,false))
     order by t.tgrelid::regclass::text,t.tgname),'[]') from pg_trigger t
   where not t.tgisinternal and (t.tgname in ('local_native_disposition_guard',
     'local_native_disposition_reference_guard','local_native_disposition_original_guard')
     or t.tgfoid='documents.local_native_disposition_row_guard_v1()'::regprocedure)),
 'relations',(select jsonb_agg(jsonb_build_object('table',c.oid::regclass::text,
     'owner',pg_get_userbyid(c.relowner),'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
     'acl',(select coalesce(jsonb_agg(a.item order by a.item::text),'[]') from
       (select jsonb_build_array(pg_get_userbyid(x.grantor),case when x.grantee=0 then 'PUBLIC' else pg_get_userbyid(x.grantee) end,x.privilege_type,x.is_grantable) item
        from aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) x) a)) order by c.oid::regclass::text)
   from pg_class c where c.oid=any(array['public.documents'::regclass,'documents.evidence_references'::regclass,
     'documents.retained_originals'::regclass,'documents.local_native_disposition_plans'::regclass,
     'documents.local_native_disposition_targets'::regclass,'documents.local_native_disposition_receipts'::regclass])),
 'policies',(select jsonb_agg(jsonb_build_object('table',p.polrelid::regclass::text,'name',p.polname,
     'command',p.polcmd,'permissive',p.polpermissive,
     'roles',(select jsonb_agg(case when r=0 then 'PUBLIC' else pg_get_userbyid(r) end order by case when r=0 then 'PUBLIC' else pg_get_userbyid(r) end) from unnest(p.polroles) r),
     'using',pg_get_expr(p.polqual,p.polrelid),'check',pg_get_expr(p.polwithcheck,p.polrelid)) order by p.polrelid::regclass::text,p.polname)
   from pg_policy p where p.polrelid=any(array['public.documents'::regclass,'documents.evidence_references'::regclass,
     'documents.retained_originals'::regclass,'documents.local_native_disposition_plans'::regclass,
     'documents.local_native_disposition_targets'::regclass,'documents.local_native_disposition_receipts'::regclass])));
"""


def native_disposition_guard_profile(target, *, generation=False):
    """The consequential native guard definitions/attachments, without catalog-wide acceptance."""
    target.validate();profile=json.loads(target._query(GUARDS_SQL))
    if (len(profile['functions'])!=6 or len(profile['triggers'])!=3 or len(profile['relations'])!=6
            or not any(p['table']=='public.documents' and p['name']=='documents_store_local_native_delete' for p in profile['policies'])):
        raise ValueError('native_recovery_guard_profile_unavailable')
    if generation:
        profile['generation']=json.loads(target._query("""set search_path='';select jsonb_build_object(
          'function',pg_get_functiondef('public.company_archive_track_source_write_v1()'::regprocedure),
          'owner',(select pg_get_userbyid(proowner) from pg_proc where oid='public.company_archive_track_source_write_v1()'::regprocedure),
          'trigger',(select jsonb_build_object('definition',pg_get_triggerdef(oid,false),'enabled',tgenabled,
            'arguments',encode(tgargs,'hex'),'type',tgtype) from pg_trigger where tgrelid='public.documents'::regclass
            and tgname='company_archive_track_documents' and tgfoid='public.company_archive_track_source_write_v1()'::regprocedure));"""))
        trigger=profile['generation']['trigger']
        if not trigger or trigger['enabled']!='O' or trigger['type']!=31 or trigger['arguments']!=b'year\0company_id\0'.hex():
            raise ValueError('native_recovery_generation_guard_unavailable')
    return profile


def verify_native_restore(target, backup_metadata, *, require_generation_guard=False):
    """Compare the complete captured census, rows, roles, files and attributes.

    Called before recovery registration or public Auth access changes any state.
    It consumes the exact metadata bytes read while verifying the full bundle
    commitment, so later path replacement cannot change the comparison inputs.
    """
    target.validate()
    binding=json.loads(backup_metadata['bindings.private.json']);expected=binding['tableFacts']
    expected_guards=binding.get('nativeDispositionGuardProfile')
    if not expected_guards:raise ValueError('native_recovery_guard_profile_unavailable')
    if require_generation_guard and 'generation' not in expected_guards:
        raise ValueError('native_recovery_generation_guard_unavailable')
    observed_guards=native_disposition_guard_profile(target,generation='generation' in expected_guards)
    if observed_guards!=expected_guards:raise ValueError('native_recovery_guard_profile_changed')
    if (not isinstance(expected,dict) or not 1<=len(expected)<=512
            or any(not isinstance(v,dict) or set(v)!={'rows','bytes','sha256'}
                or any(type(v[k]) is not int or v[k]<0 for k in ('rows','bytes'))
                or not isinstance(v['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',v['sha256']) for v in expected.values())
            or sum(v['bytes'] for v in expected.values())>32*1024*1024
            or any(not re.fullmatch(r'[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*',name) for name in expected)):
        raise ValueError('native_recovery_profile_bound')
    census=target._query("select schemaname||'.'||tablename from pg_tables where schemaname not in ('pg_catalog','information_schema') order by 1").decode().splitlines()
    if census!=sorted(expected):raise ValueError('native_recovery_table_census_changed')
    queries=[]
    for name in sorted(expected):
        schema,table=name.split('.')
        queries.append(sql.SQL("""select json_build_object('table',{},'rows',count(*),'bytes',
          octet_length(coalesce(string_agg(row_to_json(t)::text,E'\\n' order by row_to_json(t)::text collate "C"),'')||case when count(*)>0 then E'\\n' else '' end),
          'sha256',encode(sha256(convert_to(coalesce(string_agg(row_to_json(t)::text,E'\\n' order by row_to_json(t)::text collate "C"),'')||case when count(*)>0 then E'\\n' else '' end,'UTF8')),'hex'))
          from {}.{} t;""").format(sql.Literal(name),sql.Identifier(schema),sql.Identifier(table)))
    raw=target._query(sql.SQL('\n').join(queries).as_string())
    rows=[json.loads(line) for line in raw.splitlines()];observed={row.pop('table'):row for row in rows}
    if len(rows)!=len(expected) or observed!=expected:
        raise ValueError('native_recovery_table_bytes_changed')
    if sha256(target._query(ROLE_SQL)).hexdigest()!=binding['fingerprint']['roles']:
        raise ValueError('native_recovery_roles_changed')
    objects=target.objects(action='manifest')
    if objects!=json.loads(backup_metadata['object-manifest.json']):
        raise ValueError('native_recovery_all_storage_changed')
    attributes=json.loads(target._run('exec',target.storage,'node','-e',ATTRIBUTES))
    if attributes!=json.loads(backup_metadata['object-attributes.json']):
        raise ValueError('native_recovery_storage_attributes_changed')
    return {'tables':len(expected),'tableBytes':sum(v['bytes'] for v in expected.values()),
        'dispositionGuardSha256':sha256(json.dumps(observed_guards,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'rolesSha256':binding['fingerprint']['roles'],'objectManifestSha256':sha256(backup_metadata['object-manifest.json']).hexdigest(),
        'objectAttributesSha256':sha256(backup_metadata['object-attributes.json']).hexdigest()}
