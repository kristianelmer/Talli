-- Hosted projects may retain an explicit anon EXECUTE grant from older default
-- privileges even after PUBLIC is revoked. These mutation RPCs are customer
-- endpoints for authenticated owners only; each function also verifies company
-- ownership internally.
revoke all on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric, text, uuid, uuid, text
) from public, anon;
grant execute on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric, text, uuid, uuid, text
) to authenticated, service_role;

revoke all on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) from public, anon;
grant execute on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) to authenticated, service_role;

revoke all on function public.accept_bank_transaction_suggestion(uuid, text, text)
  from public, anon;
grant execute on function public.accept_bank_transaction_suggestion(uuid, text, text)
  to authenticated, service_role;
