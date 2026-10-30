-- Restore the prior case-bound support receipt policy; retained rows are untouched.
do $receipt_replay_rollback$
begin
  drop policy if exists "company year receipts reject updates"
  on public.company_access_command_receipts;

  alter policy "company access commands read receipts"
  on public.company_access_command_receipts
  using (
    actor_id = public.company_access_auth_uid_v1() and (
      command_name = 'accept_invitation'
      or (
        command_name in (
          'create_invitation', 'revoke_invitation', 'resend_invitation',
          'administer_membership', 'request_cancellation',
          'resume_cancellation', 'finalize_deletion',
          'onboard_company', 'reaccept_agreement'
        )
        and expires_at > pg_catalog.statement_timestamp()
      )
      or (
        command_name = 'review_deletion'
        and expires_at > pg_catalog.statement_timestamp()
        and support_case_id = public.company_access_current_support_case_id_v1()
        and public.company_access_has_open_support_case_v1(
          support_case_id, company_id, 'cancellation'
        )
      )
    )
  );
end;
$receipt_replay_rollback$;
