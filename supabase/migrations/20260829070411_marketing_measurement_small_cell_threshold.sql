-- Raise repeated-signal disclosure from two to five separate observations.
-- The guarded replacement upgrades databases that applied the original #196
-- migration before the founder decision. Fresh databases already contain the
-- five-observation body and take the explicit no-op branch.

begin;

select pg_catalog.set_config(
  'talli.marketing_measurement_threshold_migration_principal', current_user, true
);

do $marketing_measurement_threshold_authority$
begin
  execute pg_catalog.format(
    'grant marketing_measurement_store_owner to %I',
    current_user
  );
end
$marketing_measurement_threshold_authority$;

set local role marketing_measurement_store_owner;

do $marketing_measurement_threshold$
declare
  v_definition text;
  v_updated_definition text;
begin
  select pg_catalog.pg_get_functiondef(
    'backend_system.report_marketing_funnel_v1(integer)'::pg_catalog.regprocedure
  ) into strict v_definition;

  if pg_catalog.strpos(
    v_definition, 'having pg_catalog.count(*) >= 5'
  ) > 0 then
    return;
  end if;

  if pg_catalog.strpos(
    v_definition, 'having pg_catalog.count(*) >= 2'
  ) = 0 then
    raise exception 'marketing_measurement_threshold_source_unexpected';
  end if;

  v_updated_definition := pg_catalog.replace(
    v_definition,
    'having pg_catalog.count(*) >= 2',
    'having pg_catalog.count(*) >= 5'
  );
  execute v_updated_definition;
end
$marketing_measurement_threshold$;

reset role;

do $marketing_measurement_threshold_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke marketing_measurement_store_owner from %I',
    pg_catalog.current_setting(
      'talli.marketing_measurement_threshold_migration_principal'
    )
  );
end
$marketing_measurement_threshold_authority_revoke$;

commit;
