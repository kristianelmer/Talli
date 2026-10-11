BEGIN READ ONLY;
SET LOCAL statement_timeout = '3s';
SET LOCAL lock_timeout = '1s';
SET LOCAL search_path = pg_catalog;
WITH schemas AS (
  SELECT n.oid, n.nspowner, n.nspacl,
    jsonb_build_array('schema', n.nspname) AS identity,
    jsonb_build_array('schema', n.nspname, pg_get_userbyid(n.nspowner), n.nspacl::text) AS row
  FROM pg_namespace n WHERE n.nspname IN ('graphql', 'graphql_public')
), schema_acls AS (
  SELECT s.oid, 'grants' AS kind, coalesce(s.nspacl, acldefault('n', s.nspowner)) AS acl FROM schemas s
  UNION ALL SELECT s.oid, 'defaults', acldefault('n', s.nspowner) FROM schemas s
  UNION ALL SELECT s.oid, 'initial', i.initprivs FROM schemas s JOIN pg_init_privs i
    ON i.classoid='pg_namespace'::regclass AND i.objoid=s.oid AND i.objsubid=0
), expanded AS (
  SELECT s.oid, s.kind, coalesce(jsonb_agg(jsonb_build_array(g.rolname, a.grantee=0,
    r.rolname, a.privilege_type, a.is_grantable) ORDER BY g.rolname, a.grantee=0,
    r.rolname, a.privilege_type, a.is_grantable) FILTER (WHERE a.grantor IS NOT NULL), '[]'::jsonb) AS grants
  FROM schema_acls s LEFT JOIN LATERAL aclexplode(s.acl) a ON true
  LEFT JOIN pg_roles g ON g.oid=a.grantor LEFT JOIN pg_roles r ON r.oid=a.grantee
  GROUP BY s.oid, s.kind
), schema_rows AS (
  SELECT s.identity, s.row, acldefault('n',s.nspowner)::text AS defaults,
    (SELECT x.grants FROM expanded x WHERE x.oid=s.oid AND x.kind='grants') AS grants,
    (SELECT x.grants FROM expanded x WHERE x.oid=s.oid AND x.kind='defaults') AS default_grants,
    (SELECT coalesce(jsonb_agg(jsonb_build_array(i.privtype,i.initprivs::text,x.grants)
      ORDER BY i.privtype), '[]'::jsonb) FROM pg_init_privs i JOIN expanded x ON x.oid=s.oid AND x.kind='initial'
      WHERE i.classoid='pg_namespace'::regclass AND i.objoid=s.oid AND i.objsubid=0) AS initial,
    (SELECT coalesce(jsonb_agg(jsonb_build_array(e.extname,e.extversion,pg_get_userbyid(e.extowner))
      ORDER BY e.extname), '[]'::jsonb) FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
      WHERE d.classid='pg_namespace'::regclass AND d.objid=s.oid AND d.objsubid=0
      AND d.refclassid='pg_extension'::regclass AND d.deptype='e') AS extensions
  FROM schemas s
), functions AS (
  SELECT p.*, n.nspname, l.lanname FROM pg_proc p
  JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
  WHERE n.nspname='net' AND (
    (p.proname='http_get' AND pg_get_function_identity_arguments(p.oid)=
      'url text, params jsonb, headers jsonb, timeout_milliseconds integer') OR
    (p.proname='http_post' AND pg_get_function_identity_arguments(p.oid)=
      'url text, body jsonb, params jsonb, headers jsonb, timeout_milliseconds integer'))
), function_rows AS (
  SELECT jsonb_build_array('function',p.nspname,p.proname,pg_get_function_identity_arguments(p.oid)) AS identity,
    jsonb_build_array('function',p.nspname,p.proname,pg_get_function_identity_arguments(p.oid),
      pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig::text) AS row,
    encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex') AS definition_sha256,
    encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') AS body_sha256,
    jsonb_build_array(p.lanname,pg_get_function_result(p.oid),p.prokind,p.provolatile,p.proisstrict,
      p.proparallel,p.proleakproof,p.proretset) AS attributes,
    (SELECT jsonb_agg(jsonb_build_array(n.nspname,t.typname) ORDER BY a.ordinality)
      FROM unnest(p.proargtypes) WITH ORDINALITY a(oid,ordinality)
      JOIN pg_type t ON t.oid=a.oid JOIN pg_namespace n ON n.oid=t.typnamespace) AS types,
    (SELECT coalesce(jsonb_agg(jsonb_build_array(e.extname,e.extversion,pg_get_userbyid(e.extowner))
      ORDER BY e.extname), '[]'::jsonb) FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
      WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.objsubid=0
      AND d.refclassid='pg_extension'::regclass AND d.deptype='e') AS extensions
  FROM functions p
), hooks AS (
  SELECT jsonb_build_array('function',n.nspname,p.proname,'') AS identity,
    jsonb_build_array('function',n.nspname,p.proname,'',pg_get_userbyid(p.proowner),
      p.proacl::text,p.prosecdef,p.proconfig::text) AS row,
    encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex') AS definition_sha256,
    encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') AS body_sha256
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='extensions' AND p.pronargs=0 AND p.proname IN
    ('grant_pg_net_access','grant_pg_graphql_access','set_graphql_placeholder')
), events AS (
  SELECT e.evtname AS name, e.evtevent AS event, e.evtenabled AS enabled, e.evttags AS tags,
    pg_get_userbyid(e.evtowner) AS owner,
    jsonb_build_array('function',n.nspname,p.proname,pg_get_function_identity_arguments(p.oid)) AS function
  FROM pg_event_trigger e JOIN pg_proc p ON p.oid=e.evtfoid JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE e.evtname IN ('issue_pg_net_access','issue_pg_graphql_access','issue_graphql_placeholder')
)
SELECT jsonb_build_object(
  'serverVersion',current_setting('server_version_num')::integer,
  'schemas',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.identity::text),'[]'::jsonb) FROM schema_rows s),
  'functions',(SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.identity::text),'[]'::jsonb) FROM function_rows f),
  'hooks',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.identity::text),'[]'::jsonb) FROM hooks h),
  'events',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.name),'[]'::jsonb) FROM events e),
  'extensions',(SELECT coalesce(jsonb_agg(jsonb_build_array(e.extname,e.extversion,n.nspname,
    pg_get_userbyid(e.extowner)) ORDER BY e.extname),'[]'::jsonb)
    FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname IN ('pg_net','pg_graphql')));
ROLLBACK;
