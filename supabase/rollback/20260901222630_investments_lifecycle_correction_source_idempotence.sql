-- BOUNDED ROLLBACK ARTIFACT: retain the insert-only correction-source fix.
-- Reintroducing ON CONFLICT DO UPDATE would restore a known forced-RLS failure
-- and would not restore data or a legitimate predecessor runtime.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'talli:investments:lifecycle-correction-source-idempotence',
    0
  )
);

do $retained_safety_check$
declare
  v_definition text;
begin
  select pg_catalog.pg_get_functiondef(
    'investments.record_lifecycle_correction_sources_v2(uuid,uuid,jsonb)'::regprocedure
  ) into strict v_definition;

  if v_definition !~* 'ON CONFLICT[[:space:][:print:]]+DO NOTHING'
    or v_definition !~* 'registered[.]fact_sha256 = item ->> ''factSha256'''
    or v_definition ~* 'DO UPDATE SET fact_sha256'
  then
    raise exception 'investments_correction_source_idempotence_rollback_unsafe';
  end if;
end
$retained_safety_check$;

commit;
