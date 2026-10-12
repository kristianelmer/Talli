-- Immutable supported events have SELECT/INSERT-only forced RLS. FOR UPDATE
-- hides committed rows behind the absent UPDATE policy and defeats replay.
-- Company-first and event-next advisory guards already serialize these writers.
-- Remove only that row-lock clause; preserve every authority and fresh check.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table governance_replay_visibility_roles(role_name text,prior jsonb) on commit drop;
create temporary table governance_replay_visibility_create(added boolean) on commit drop;
do $borrow$
declare name text; prior jsonb; schema_owner text;
begin
 select pg_catalog.pg_get_userbyid(nspowner) into strict schema_owner
  from pg_catalog.pg_namespace where nspname='corporate_governance';
 if (select count(*)=1 and bool_and(p.proowner=pg_catalog.to_regrole('corporate_governance_store_owner'))
     from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
     where n.nspname='corporate_governance' and p.proname='complete_supported_event_v1'
      and p.prokind='f' and pg_catalog.oidvectortypes(p.proargtypes)='jsonb, text') is distinct from true
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
 for name in select distinct value from unnest(array['corporate_governance_store_owner',schema_owner]) value loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into prior
    from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
     and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.governance_replay_visibility_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.governance_replay_visibility_create
  select not pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE');
 if (select added from pg_temp.governance_replay_visibility_create) then
  execute pg_catalog.format('set local role %I',schema_owner);
  grant create on schema corporate_governance to corporate_governance_store_owner;
  reset role;
 end if;
end; $borrow$;
set local role corporate_governance_store_owner;
do $repair$
declare before_row pg_catalog.pg_proc%rowtype; after_row pg_catalog.pg_proc%rowtype;
 definition text; repaired text; owner_had_execute boolean;
begin
 select * into before_row from pg_catalog.pg_proc
  where oid='corporate_governance.complete_supported_event_v1(jsonb,text)'::regprocedure;
 if before_row.proowner<>current_user::regrole or not before_row.prosecdef
  or before_row.provolatile<>'v' or before_row.prokind<>'f'
  or before_row.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or before_row.proconfig is distinct from array['search_path=""']::text[]
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
 -- MD5 identifies the exact released SQL body; it is not an evidence digest.
 if pg_catalog.md5(before_row.prosrc)='93c0f6bb1c2eb4b6077ab1163e60c77c' then return; end if;
 if pg_catalog.md5(before_row.prosrc)<>'70a79755f5ca97e2fe8ee7e697b54993'
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
 repaired:=pg_catalog.replace(before_row.prosrc,
  E'  where event.event_id = v_event_id\n  for update;',
  '  where event.event_id = v_event_id;');
 if pg_catalog.md5(repaired)<>'93c0f6bb1c2eb4b6077ab1163e60c77c'
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
 definition:=pg_catalog.pg_get_functiondef(before_row.oid);
 if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,''))<>pg_catalog.length(before_row.prosrc)
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
 owner_had_execute:=pg_catalog.has_function_privilege(current_user,before_row.oid,'EXECUTE');
 if not owner_had_execute then execute pg_catalog.format('grant execute on function %s to %I',before_row.oid::regprocedure,current_user); end if;
 execute pg_catalog.replace(definition,before_row.prosrc,repaired);
 if not owner_had_execute then execute pg_catalog.format('revoke execute on function %s from %I',before_row.oid::regprocedure,current_user); end if;
 select * into after_row from pg_catalog.pg_proc where oid=before_row.oid;
 if (pg_catalog.to_jsonb(after_row)-'prosrc') is distinct from (pg_catalog.to_jsonb(before_row)-'prosrc')
 then raise exception 'corporate_governance_replay_definition_drift'; end if;
end; $repair$;
reset role;
do $restore$
declare item record; schema_owner text;
begin
 if (select added from pg_temp.governance_replay_visibility_create) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='corporate_governance';
  execute pg_catalog.format('set local role %I',schema_owner);
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.governance_replay_visibility_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
