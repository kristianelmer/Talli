-- Roll back operator application authority before the owning table expansion.
-- Original audit rows and the predecessor service-role overlap are preserved.
begin;
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner to %I',current_user);
end;
$membership$;
drop function authority_connections.list_operations_v1(integer);
drop function authority_connections.complete_operation_v1(uuid,text,text,integer);
drop function authority_connections.begin_operation_v1(uuid,text,text,jsonb);
drop function authority_connections.assert_operator_v1(boolean);
drop policy authority_operations_admin_read on authority_connections.authority_operations;
drop policy authority_operations_admin_insert on authority_connections.authority_operations;
drop policy authority_operations_admin_update on authority_connections.authority_operations;
revoke insert,update on authority_connections.authority_operations from authority_connections_store_owner;
do $cleanup$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner from %I',current_user);
end;
$cleanup$;
commit;
