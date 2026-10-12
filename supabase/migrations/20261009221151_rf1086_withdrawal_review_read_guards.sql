-- Current review reads reject withdrawn evidence. Shared historical/replay
-- internals remain byte-for-byte unchanged; no new grants or writer activation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_review_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m
   where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_withdrawal_review_role values(prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Guard only references in the frozen source codec; not a second economics or
-- Governance-enumeration implementation. Both overloads require held scope locks.
do $review_guards$
declare spec record; before_row pg_catalog.pg_proc%rowtype; after_row pg_catalog.pg_proc%rowtype;
 old_body text; new_body text; definition text;
begin
 for spec in select * from (values
  ('shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text)',
   'shareholder_register_filing.source_approval_context_internal_v1(p_preview,p_entitlement,p_subject)'),
  ('shareholder_register_filing.read_source_approval_context_v2(uuid,uuid,text,text)',
   'shareholder_register_filing.source_approval_context_internal_v2(p_preview,p_entitlement,p_annual_text,p_subject)')
 ) reads(identity,context_call) loop
  select * into before_row from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(spec.identity);
  if before_row.oid is null or before_row.proowner<>current_user::regrole or not before_row.prosecdef
   or before_row.provolatile<>'v' or before_row.proconfig is distinct from array['search_path=""']::text[]
  then raise exception 'rf1086_withdrawal_review_definition_drift'; end if;
  old_body:='select '||spec.context_call||'-''reviewText'';';
  new_body:=E'\ndeclare context jsonb;\nbegin\n context:='||spec.context_call||E';\n'
   ||E' -- rf1086_withdrawal_current_review_guard_v1\n'
   ||E' perform shareholder_register_filing.assert_source_register_observations_active_internal_v1(\n'
   ||E'  (context->>''companyId'')::uuid,(context->>''incomeYear'')::integer,\n'
   ||E'  (context->>''sourceId'')::uuid,context->>''sourceSha256'');\n'
   ||E' return context-''reviewText'';\nend; ';
  if before_row.prosrc=new_body and before_row.prolang=(select oid from pg_catalog.pg_language where lanname='plpgsql')
  then continue; end if;
  if pg_catalog.btrim(before_row.prosrc,E' \n\r\t') is distinct from old_body
   or before_row.prolang<>(select oid from pg_catalog.pg_language where lanname='sql')
  then raise exception 'rf1086_withdrawal_review_definition_drift'; end if;
  definition:=pg_catalog.pg_get_functiondef(before_row.oid);
  if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,''))<>pg_catalog.length(before_row.prosrc)
   or pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,'LANGUAGE sql',''))<>pg_catalog.length('LANGUAGE sql')
  then raise exception 'rf1086_withdrawal_review_definition_drift'; end if;
  definition:=pg_catalog.replace(definition,before_row.prosrc,new_body);
  execute pg_catalog.replace(definition,'LANGUAGE sql','LANGUAGE plpgsql');
  select * into after_row from pg_catalog.pg_proc where oid=before_row.oid;
  if (pg_catalog.to_jsonb(after_row)-array['prosrc','prolang'])
   is distinct from (pg_catalog.to_jsonb(before_row)-array['prosrc','prolang'])
  then raise exception 'rf1086_withdrawal_review_definition_drift'; end if;
 end loop;
end; $review_guards$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_review_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
