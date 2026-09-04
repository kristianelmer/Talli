-- Roll back the additive supported corporate-event source (#191).
begin;

select pg_catalog.set_config(
  'talli.corporate_governance_191_rollback_had_store_owner',
  pg_catalog.pg_has_role(
    current_user, 'corporate_governance_store_owner', 'member'
  )::text,
  true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner to %I', current_user
  );
end
$membership$;

drop function if exists corporate_governance.list_supported_events_v1(
  uuid[], text
);
drop function if exists corporate_governance.complete_supported_event_v1(
  jsonb, text
);
drop function if exists corporate_governance.prepare_supported_event_v1(
  jsonb, text
);
drop function if exists corporate_governance.supported_event_result_v1(
  uuid, boolean
);

set local role corporate_governance_store_owner;
drop table if exists corporate_governance.supported_events;
reset role;

do $membership_revoke$
begin
  if pg_catalog.current_setting(
    'talli.corporate_governance_191_rollback_had_store_owner'
  )::boolean is false then
    execute pg_catalog.format(
      'revoke corporate_governance_store_owner from %I', current_user
    );
  end if;
end
$membership_revoke$;

commit;
