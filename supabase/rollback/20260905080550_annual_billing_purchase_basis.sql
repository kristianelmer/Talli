begin;
-- Remove authority only. Existing acceptance and purchase evidence is retained.
do $borrow_authority$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
end;
$borrow_authority$;
set local role company_access_executor;
drop function public.company_access_purchase_basis_v1(uuid, integer, uuid, uuid);
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end;
$return_authority$;
commit;
