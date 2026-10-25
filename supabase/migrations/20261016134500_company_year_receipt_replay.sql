-- Company-year receipts outlive delivery tokens so retries retain their result.
-- Keep them immutable even when another permissive policy allows token cleanup.
do $receipt_replay$
begin
  alter policy "company access commands read receipts"
  on public.company_access_command_receipts
  using (
    actor_id = public.company_access_auth_uid_v1() and (
      command_name in ('accept_invitation', 'admit_company_year', 'recheck_company_year_eligibility')
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

  -- Historical support rehearsals replace SELECT but retain this UPDATE guard.
  -- Recreate it atomically so the exact successor can be replayed afterward.
  drop policy if exists "company year receipts reject updates"
  on public.company_access_command_receipts;
  create policy "company year receipts reject updates"
  on public.company_access_command_receipts
  as restrictive for update
  to company_access_executor, company_access_recovery_executor
  using (command_name not in ('admit_company_year', 'recheck_company_year_eligibility'))
  with check (command_name not in ('admit_company_year', 'recheck_company_year_eligibility'));
end;
$receipt_replay$;
