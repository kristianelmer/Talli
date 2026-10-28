"""Finite native backup/target comparison for the owned offline recovery adapter."""
import json
import re
from hashlib import sha256
from pathlib import Path

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


def verify_native_restore(target, backup_directory):
    """Compare the complete captured census, rows, roles, files and attributes.

    Called before recovery registration or public Auth access changes any state.
    It consumes a bundle whose full file commitment was checked independently.
    """
    target.validate();directory=Path(backup_directory)
    binding=json.loads((directory/'bindings.private.json').read_bytes());expected=binding['tableFacts']
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
    if objects!=json.loads((directory/'object-manifest.json').read_bytes()):
        raise ValueError('native_recovery_all_storage_changed')
    attributes=json.loads(target._run('exec',target.storage,'node','-e',ATTRIBUTES))
    if attributes!=json.loads((directory/'object-attributes.json').read_bytes()):
        raise ValueError('native_recovery_storage_attributes_changed')
    return {'tables':len(expected),'tableBytes':sum(v['bytes'] for v in expected.values()),
        'rolesSha256':binding['fingerprint']['roles'],'objectManifestSha256':sha256((directory/'object-manifest.json').read_bytes()).hexdigest(),
        'objectAttributesSha256':sha256((directory/'object-attributes.json').read_bytes()).hexdigest()}
