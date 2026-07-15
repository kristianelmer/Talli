insert into auth.users (id, email) values
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'owner@example.test'),
  ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'other@example.test');

insert into public.companies (id, org_number, name, entity_type, created_by) values
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '310279617', 'LOGISK ØDE TIGER AS', 'AS', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
  ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', '310188743', 'HUSLØS STABIL TIGER AS', 'AS', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc');

insert into public.company_memberships (company_id, user_id, role, accepted_at) values
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'owner', now()),
  ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'owner', now());

insert into public.annual_data (
  id, company_id, income_year, answers, completed_by, updated_by
) values (
  '33333333-3333-4333-8333-333333333333',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  2024,
  '{"general_meeting_approved": true}'::jsonb,
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.annual_data (
  id, company_id, income_year, answers, completed_by, updated_by
) values (
  'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  2025,
  '{}'::jsonb,
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.annual_data (
  id, company_id, income_year, answers, completed_by, updated_by
) values (
  'ffffffff-ffff-4fff-8fff-ffffffffffff',
  'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
  2025,
  '{}'::jsonb,
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
);

insert into public.opening_balance_setups (
  id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, created_by
) values (
  '10101010-1010-4010-8010-101010101010',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  2025,
  500000,
  200000,
  1000,
  200,
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.opening_shareholders (
  id, setup_id, company_id, name, shareholder_kind, national_id, share_count, created_by
) values
  (
    '10101010-1010-4010-8010-101010101011',
    '10101010-1010-4010-8010-101010101010',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'Åse Nordmann',
    'norwegian_person',
    '01017012345',
    600,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  ),
  (
    '10101010-1010-4010-8010-101010101012',
    '10101010-1010-4010-8010-101010101010',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'Jørgen Østby',
    'norwegian_person',
    '02027012345',
    400,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );

insert into public.ledger_entries (
  id, company_id, income_year, entry_type, memo, lines, created_by
) values
  (
    '10101010-1010-4010-8010-101010101021',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2024,
    'opening_balance',
    'Approved 2024 opening balances',
    '[
      {"account":"1920","debit":375000,"credit":0},
      {"account":"2000","debit":0,"credit":200000},
      {"account":"2050","debit":0,"credit":175000}
    ]'::jsonb,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  ),
  (
    '10101010-1010-4010-8010-101010101022',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2024,
    'dividend_received',
    'Approved 2024 financial income',
    '[
      {"account":"1920","debit":125000,"credit":0},
      {"account":"8070","debit":0,"credit":125000}
    ]'::jsonb,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  ),
  (
    '10101010-1010-4010-8010-101010101023',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2025,
    'opening_balance',
    '2025 opening balances',
    '[
      {"account":"1920","debit":500000,"credit":0},
      {"account":"2000","debit":0,"credit":200000},
      {"account":"2050","debit":0,"credit":300000}
    ]'::jsonb,
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );

set role authenticated;
set request.jwt.claim.sub = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
select set_config(
  'request.jwt.claims',
  jsonb_build_object(
    'sub', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aal', 'aal2',
    'amr', jsonb_build_array(
      jsonb_build_object(
        'method', 'totp',
        'timestamp', floor(extract(epoch from now()))::bigint
      )
    )
  )::text,
  false
);

create temporary table rehearsal_inputs (payload jsonb not null);
insert into rehearsal_inputs (payload) values (
  $json$
  {
    "decision": {
      "id": "11111111-1111-4111-8111-111111111111",
      "company_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "income_year": 2025,
      "decision_kind": "owner_dividend",
      "annual_close_source_id": "33333333-3333-4333-8333-333333333333",
      "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "canonical_input": {
        "request_id": "11111111-1111-4111-8111-111111111111",
        "company_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "organization_number": "310279617",
        "legal_name": "LOGISK ØDE TIGER AS",
        "income_year": 2025,
        "annual_basis_year": 2024,
        "decision_kind": "owner_dividend",
        "annual_close_source_id": "33333333-3333-4333-8333-333333333333",
        "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "template_family": "norwegian_simple_as",
        "template_version": "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1",
        "financial_totals": {
          "result_after_tax_ore": 12500000,
          "equity_ore": 50000000,
          "available_distribution_ore": 30000000,
          "cash_ore": 50000000
        },
        "board_meeting": {
          "meeting_date": "2025-06-10",
          "meeting_time": "09:00:00",
          "place": "Os",
          "treatment_method": "physical"
        },
        "board_participants": [
          {"participant_id": "board-1", "name": "Åse Nordmann", "role": "chair"},
          {"participant_id": "board-2", "name": "Jørgen Østby", "role": "member"}
        ],
        "general_meeting": {
          "meeting_date": "2025-06-20",
          "meeting_time": "10:00:00",
          "place": "Os",
          "meeting_form": "physical",
          "chair_name": "Åse Nordmann",
          "co_signer_name": "Jørgen Østby"
        },
        "shareholders": [
          {
            "shareholder_id": "10101010-1010-4010-8010-101010101011",
            "name": "Åse Nordmann",
            "share_count": 600,
            "represented_share_count": 600,
            "vote": "for"
          },
          {
            "shareholder_id": "10101010-1010-4010-8010-101010101012",
            "name": "Jørgen Østby",
            "share_count": 400,
            "represented_share_count": 400,
            "vote": "for"
          }
        ],
        "total_company_shares": 1000,
        "one_share_class_confirmed": true,
        "dividend": {
          "amount_ore": 10000000,
          "payment_date": "2025-07-01",
          "liquidity_after_payment_ore": 40000000,
          "allocations": [
            {"shareholder_id": "10101010-1010-4010-8010-101010101011", "amount_ore": 6000000},
            {"shareholder_id": "10101010-1010-4010-8010-101010101012", "amount_ore": 4000000}
          ]
        },
        "annual_result_allocation_ore": 12500000,
        "confirmations": {
          "latest_approved_annual_accounts": true,
          "supported_dividend_basis": true,
          "full_board_participation": true,
          "full_share_representation": true,
          "unanimous_board": true,
          "unanimous_shareholders": true,
          "proportional_allocation": true,
          "prudent_equity_and_liquidity": true
        }
      },
      "decision_hash": "89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82"
    },
    "document_set": {
      "id": "12111111-1111-4111-8111-111111111111",
      "template_family": "norwegian_simple_as",
      "template_version": "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1",
      "decision_hash": "89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82"
    },
    "artifacts": [
      {
        "id": "13111111-1111-4111-8111-111111111111",
        "document_id": "14111111-1111-4111-8111-111111111111",
        "artifact_kind": "dividend_board_proposal",
        "name": "styrets-forslag-til-utbytte.pdf",
        "content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "byte_length": 5000,
        "mime_type": "application/pdf",
        "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/12111111-1111-4111-8111-111111111111/dividend_board_proposal/1111111111111111111111111111111111111111111111111111111111111111.pdf"
      },
      {
        "id": "15111111-1111-4111-8111-111111111111",
        "document_id": "16111111-1111-4111-8111-111111111111",
        "artifact_kind": "dividend_general_meeting_minutes",
        "name": "generalforsamlingsprotokoll-utbytte.pdf",
        "content_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
        "byte_length": 5100,
        "mime_type": "application/pdf",
        "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/12111111-1111-4111-8111-111111111111/dividend_general_meeting_minutes/2222222222222222222222222222222222222222222222222222222222222222.pdf"
      }
    ],
    "idempotency_key": "draft-owner-dividend-1"
  }
  $json$::jsonb
);

do $$
declare
  v_forged_payload jsonb;
begin
  v_forged_payload := jsonb_set(
    (select payload from rehearsal_inputs),
    '{decision,canonical_input,financial_totals,available_distribution_ore}',
    to_jsonb(999999999999::bigint)
  );
  v_forged_payload := jsonb_set(
    v_forged_payload,
    '{decision,decision_hash}',
    to_jsonb('dd2f40078029c965aa72a27fa2ae66fb5cf83c446b4a3cefb9edd2f83c4a2643'::text)
  );
  v_forged_payload := jsonb_set(
    v_forged_payload,
    '{document_set,decision_hash}',
    to_jsonb('dd2f40078029c965aa72a27fa2ae66fb5cf83c446b4a3cefb9edd2f83c4a2643'::text)
  );
  v_forged_payload := jsonb_set(
    v_forged_payload,
    '{idempotency_key}',
    to_jsonb('draft-owner-dividend-forged-financials'::text)
  );
  begin
    perform public.create_corporate_document_draft(v_forged_payload);
    raise exception 'expected_persisted_facts_mismatch_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_persisted_facts_mismatch%' then
        raise;
      end if;
  end;
end;
$$;

select public.create_corporate_document_draft((select payload from rehearsal_inputs));
select public.create_corporate_document_draft((select payload from rehearsal_inputs));

do $$
begin
  begin
    perform public.create_corporate_document_draft(
      jsonb_set(
        (select payload from rehearsal_inputs),
        '{decision,decision_hash}',
        to_jsonb('ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'::text)
      )
    );
    raise exception 'expected_idempotency_conflict_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_idempotency_conflict%' then
        raise;
      end if;
  end;
end;
$$;

select public.record_corporate_document_event(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'event_kind', 'facts_approved',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'metadata', jsonb_build_object('reviewed_artifact_count', 2),
    'idempotency_key', 'owner-dividend-facts-approved-1'
  )
);

do $$
begin
  begin
    perform public.attest_corporate_signed_artifact(
      $json$
      {
        "decision_id": "11111111-1111-4111-8111-111111111111",
        "set_id": "12111111-1111-4111-8111-111111111111",
        "unsigned_artifact_id": "13111111-1111-4111-8111-111111111111",
        "decision_hash": "89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82",
        "signers": ["Åse Nordmann"],
        "signed_artifact": {
          "id": "17111111-1111-4111-8111-111111111111",
          "document_id": "18111111-1111-4111-8111-111111111111",
          "artifact_kind": "dividend_board_proposal",
          "name": "signert-styreforslag.pdf",
          "content_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
          "byte_length": 6000,
          "mime_type": "application/pdf",
          "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/12111111-1111-4111-8111-111111111111/dividend_board_proposal/3333333333333333333333333333333333333333333333333333333333333333.pdf"
        },
        "idempotency_key": "owner-dividend-board-signed-missing-signer"
      }
      $json$::jsonb
    );
    raise exception 'expected_missing_signers_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_missing_signers%' then
        raise;
      end if;
  end;
end;
$$;

select public.attest_corporate_signed_artifact(
  $json$
  {
    "decision_id": "11111111-1111-4111-8111-111111111111",
    "set_id": "12111111-1111-4111-8111-111111111111",
    "unsigned_artifact_id": "13111111-1111-4111-8111-111111111111",
    "decision_hash": "89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82",
    "signers": ["Åse Nordmann", "Jørgen Østby"],
    "signed_artifact": {
      "id": "17111111-1111-4111-8111-111111111111",
      "document_id": "18111111-1111-4111-8111-111111111111",
      "artifact_kind": "dividend_board_proposal",
      "name": "signert-styreforslag.pdf",
      "content_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
      "byte_length": 6000,
      "mime_type": "application/pdf",
      "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/12111111-1111-4111-8111-111111111111/dividend_board_proposal/3333333333333333333333333333333333333333333333333333333333333333.pdf"
    },
    "idempotency_key": "owner-dividend-board-signed-1"
  }
  $json$::jsonb
);

do $$
begin
  begin
    perform public.finalize_corporate_decision(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'finalization_id', '21111111-1111-4111-8111-111111111111',
        'holding_action_id', '22111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-finalized-before-all-signatures'
      )
    );
    raise exception 'expected_missing_signed_artifacts_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_missing_signed_artifacts%' then
        raise;
      end if;
  end;
end;
$$;

select public.attest_corporate_signed_artifact(
  $json$
  {
    "decision_id": "11111111-1111-4111-8111-111111111111",
    "set_id": "12111111-1111-4111-8111-111111111111",
    "unsigned_artifact_id": "15111111-1111-4111-8111-111111111111",
    "decision_hash": "89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82",
    "signers": ["Åse Nordmann", "Jørgen Østby"],
    "signed_artifact": {
      "id": "19111111-1111-4111-8111-111111111111",
      "document_id": "20111111-1111-4111-8111-111111111111",
      "artifact_kind": "dividend_general_meeting_minutes",
      "name": "signert-generalforsamlingsprotokoll.pdf",
      "content_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
      "byte_length": 6100,
      "mime_type": "application/pdf",
      "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/12111111-1111-4111-8111-111111111111/dividend_general_meeting_minutes/4444444444444444444444444444444444444444444444444444444444444444.pdf"
    },
    "idempotency_key": "owner-dividend-general-meeting-signed-1"
  }
  $json$::jsonb
);

select public.record_corporate_document_event(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'event_kind', 'signing_requested',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'metadata', '{}'::jsonb,
    'idempotency_key', 'owner-dividend-signing-requested-1'
  )
);

do $$
begin
  begin
    perform public.finalize_corporate_decision(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'finalization_id', '21111111-1111-4111-8111-111111111111',
        'holding_action_id', '22111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-finalized-without-policy'
      )
    );
    raise exception 'expected_accounting_policy_disabled_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_accounting_policy_disabled%' then
        raise;
      end if;
  end;
end;
$$;

reset role;

insert into public.corporate_accounting_policies (
  policy_version,
  declaration_debit_account,
  dividend_payable_account,
  bank_account,
  reviewer,
  reviewed_at,
  evidence_reference,
  enabled,
  recorded_by
) values (
  'rehearsal-policy-v1',
  '2080',
  '2920',
  '1920',
  'Synthetic rehearsal reviewer',
  now(),
  'tests/fixtures/corporate_documents/database_rehearsal.sql',
  true,
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

set role authenticated;
set request.jwt.claim.sub = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

do $$
begin
  begin
    insert into public.ledger_entries (
      id, company_id, income_year, entry_type, memo, lines, created_by
    ) values (
      '10101010-1010-4010-8010-101010101024',
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      2024,
      'expense',
      'Source changed after owner approval',
      '[
        {"account":"7770","debit":100,"credit":0},
        {"account":"1920","debit":0,"credit":100}
      ]'::jsonb,
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    );
    perform public.finalize_corporate_decision(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'finalization_id', '21111111-1111-4111-8111-111111111111',
        'holding_action_id', '22111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-finalized-after-source-change'
      )
    );
    raise exception 'expected_persisted_facts_mismatch_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_persisted_facts_mismatch%' then
        raise;
      end if;
  end;
end;
$$;

do $$
begin
  begin
    insert into public.period_locks (company_id, income_year, reason, locked_by) values (
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      2025,
      'Temporary finalization lock rehearsal',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    );
    perform public.finalize_corporate_decision(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'finalization_id', '21111111-1111-4111-8111-111111111111',
        'holding_action_id', '22111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-finalized-while-locked'
      )
    );
    raise exception 'expected_income_year_locked_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_income_year_locked%' then
        raise;
      end if;
  end;
end;
$$;

select public.finalize_corporate_decision(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'finalization_id', '21111111-1111-4111-8111-111111111111',
    'holding_action_id', '22111111-1111-4111-8111-111111111111',
    'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
    'idempotency_key', 'owner-dividend-finalized-1'
  )
);

insert into public.bank_transactions (
  id, company_id, income_year, transaction_date, text, amount, source_hash, created_by
) values
  (
    '24111111-1111-4111-8111-111111111111',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2025,
    '2025-07-01',
    'Utbetaling utbytte del 1',
    -60000.00,
    '5555555555555555555555555555555555555555555555555555555555555555',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  ),
  (
    '27111111-1111-4111-8111-111111111111',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2025,
    '2025-07-02',
    'Utbetaling utbytte del 2',
    -40000.00,
    '6666666666666666666666666666666666666666666666666666666666666666',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  ),
  (
    '30111111-1111-4111-8111-111111111111',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    2025,
    '2025-07-03',
    'Utbetaling som overstiger restgjeld',
    -1.00,
    '7777777777777777777777777777777777777777777777777777777777777777',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );

select public.record_owner_dividend_payment(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'bank_transaction_id', '24111111-1111-4111-8111-111111111111',
    'holding_action_id', '25111111-1111-4111-8111-111111111111',
    'ledger_entry_id', '26111111-1111-4111-8111-111111111111',
    'idempotency_key', 'owner-dividend-payment-1'
  )
);

reset role;

do $$
declare
  v_payload jsonb;
begin
  select payload into v_payload from rehearsal_inputs;
  v_payload := (replace(
    replace(
      replace(
        replace(
          replace(
            replace(
              replace(v_payload::text,
                '11111111-1111-4111-8111-111111111111', '33111111-1111-4111-8111-111111111111'),
              '12111111-1111-4111-8111-111111111111', '34111111-1111-4111-8111-111111111111'),
            '13111111-1111-4111-8111-111111111111', '35111111-1111-4111-8111-111111111111'),
          '14111111-1111-4111-8111-111111111111', '36111111-1111-4111-8111-111111111111'),
        '15111111-1111-4111-8111-111111111111', '37111111-1111-4111-8111-111111111111'),
      '16111111-1111-4111-8111-111111111111', '38111111-1111-4111-8111-111111111111'),
    '33333333-3333-4333-8333-333333333333', 'ffffffff-ffff-4fff-8fff-ffffffffffff'))::jsonb;
  v_payload := jsonb_set(v_payload, '{idempotency_key}', to_jsonb('cross-company-source-draft'::text));
  begin
    perform public.create_corporate_document_draft(v_payload);
    raise exception 'expected_cross_company_source_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_cross_company_source%' then
        raise;
      end if;
  end;
end;
$$;

select public.record_owner_dividend_payment(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'bank_transaction_id', '24111111-1111-4111-8111-111111111111',
    'holding_action_id', '25111111-1111-4111-8111-111111111111',
    'ledger_entry_id', '26111111-1111-4111-8111-111111111111',
    'idempotency_key', 'owner-dividend-payment-1'
  )
);

select public.record_owner_dividend_payment(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'bank_transaction_id', '27111111-1111-4111-8111-111111111111',
    'holding_action_id', '28111111-1111-4111-8111-111111111111',
    'ledger_entry_id', '29111111-1111-4111-8111-111111111111',
    'idempotency_key', 'owner-dividend-payment-2'
  )
);

do $$
begin
  begin
    perform public.record_owner_dividend_payment(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'bank_transaction_id', '30111111-1111-4111-8111-111111111111',
        'holding_action_id', '31111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '32111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-payment-over-limit'
      )
    );
    raise exception 'expected_payment_exceeds_payable_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_payment_exceeds_payable%' then
        raise;
      end if;
  end;
end;
$$;

select public.finalize_corporate_decision(
  jsonb_build_object(
    'decision_id', '11111111-1111-4111-8111-111111111111',
    'set_id', '12111111-1111-4111-8111-111111111111',
    'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
    'finalization_id', '21111111-1111-4111-8111-111111111111',
    'holding_action_id', '22111111-1111-4111-8111-111111111111',
    'ledger_entry_id', '23111111-1111-4111-8111-111111111111',
    'idempotency_key', 'owner-dividend-finalized-1'
  )
);

update public.annual_data
set answers = jsonb_build_object('general_meeting_approved', true),
    updated_at = now()
where id = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';

insert into public.period_locks (company_id, income_year, reason, locked_by) values (
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  2025,
  'Annual figures are closed before annual meeting artifacts are created.',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

do $$
begin
  begin
    perform public.record_owner_dividend_payment(
      jsonb_build_object(
        'decision_id', '11111111-1111-4111-8111-111111111111',
        'set_id', '12111111-1111-4111-8111-111111111111',
        'decision_hash', '89797b2574133d0c08171b2f49f878e42318b5423ef48fb9d42545373f5a0b82',
        'bank_transaction_id', '30111111-1111-4111-8111-111111111111',
        'holding_action_id', '31111111-1111-4111-8111-111111111111',
        'ledger_entry_id', '32111111-1111-4111-8111-111111111111',
        'idempotency_key', 'owner-dividend-payment-while-locked'
      )
    );
    raise exception 'expected_income_year_locked_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_documents_income_year_locked%' then
        raise;
      end if;
  end;
end;
$$;

create temporary table annual_rehearsal_inputs (payload jsonb not null);
insert into annual_rehearsal_inputs (payload) values (
  $json$
  {
    "decision": {
      "id": "41111111-1111-4111-8111-111111111111",
      "company_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "income_year": 2025,
      "decision_kind": "annual_close",
      "annual_close_source_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      "source_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "canonical_input": {
        "request_id": "41111111-1111-4111-8111-111111111111",
        "company_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "organization_number": "310279617",
        "legal_name": "LOGISK ØDE TIGER AS",
        "income_year": 2025,
        "annual_basis_year": 2025,
        "decision_kind": "annual_close",
        "annual_close_source_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "source_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "template_family": "norwegian_simple_as",
        "template_version": "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1",
        "financial_totals": {
          "result_after_tax_ore": 0,
          "equity_ore": 50000000,
          "available_distribution_ore": 30000000,
          "cash_ore": 40000000
        },
        "board_meeting": {
          "meeting_date": "2026-05-01",
          "meeting_time": "09:00:00",
          "place": "Os",
          "treatment_method": "physical"
        },
        "board_participants": [
          {"participant_id": "board-1", "name": "Åse Nordmann", "role": "chair"},
          {"participant_id": "board-2", "name": "Jørgen Østby", "role": "member"}
        ],
        "general_meeting": {
          "meeting_date": "2026-05-10",
          "meeting_time": "10:00:00",
          "place": "Os",
          "meeting_form": "physical",
          "chair_name": "Åse Nordmann",
          "co_signer_name": "Jørgen Østby"
        },
        "shareholders": [
          {
            "shareholder_id": "10101010-1010-4010-8010-101010101011",
            "name": "Åse Nordmann",
            "share_count": 600,
            "represented_share_count": 600,
            "vote": "for"
          },
          {
            "shareholder_id": "10101010-1010-4010-8010-101010101012",
            "name": "Jørgen Østby",
            "share_count": 400,
            "represented_share_count": 400,
            "vote": "for"
          }
        ],
        "total_company_shares": 1000,
        "one_share_class_confirmed": true,
        "dividend": null,
        "annual_result_allocation_ore": 0,
        "confirmations": {
          "latest_approved_annual_accounts": true,
          "supported_dividend_basis": true,
          "full_board_participation": true,
          "full_share_representation": true,
          "unanimous_board": true,
          "unanimous_shareholders": true,
          "proportional_allocation": true,
          "prudent_equity_and_liquidity": true
        }
      },
      "decision_hash": "f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923"
    },
    "document_set": {
      "id": "42111111-1111-4111-8111-111111111111",
      "template_family": "norwegian_simple_as",
      "template_version": "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1",
      "decision_hash": "f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923"
    },
    "artifacts": [
      {
        "id": "43111111-1111-4111-8111-111111111111",
        "document_id": "44111111-1111-4111-8111-111111111111",
        "artifact_kind": "annual_board_minutes",
        "name": "styreprotokoll-aarsregnskap.pdf",
        "content_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
        "byte_length": 5200,
        "mime_type": "application/pdf",
        "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/42111111-1111-4111-8111-111111111111/annual_board_minutes/8888888888888888888888888888888888888888888888888888888888888888.pdf"
      },
      {
        "id": "45111111-1111-4111-8111-111111111111",
        "document_id": "46111111-1111-4111-8111-111111111111",
        "artifact_kind": "annual_general_meeting_minutes",
        "name": "generalforsamlingsprotokoll-aarsregnskap.pdf",
        "content_sha256": "9999999999999999999999999999999999999999999999999999999999999998",
        "byte_length": 5300,
        "mime_type": "application/pdf",
        "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/42111111-1111-4111-8111-111111111111/annual_general_meeting_minutes/9999999999999999999999999999999999999999999999999999999999999998.pdf"
      }
    ],
    "idempotency_key": "annual-close-draft-1"
  }
  $json$::jsonb
);

select public.create_corporate_document_draft((select payload from annual_rehearsal_inputs));

select public.record_corporate_document_event(
  jsonb_build_object(
    'decision_id', '41111111-1111-4111-8111-111111111111',
    'set_id', '42111111-1111-4111-8111-111111111111',
    'event_kind', 'facts_approved',
    'decision_hash', 'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923',
    'metadata', jsonb_build_object('reviewed_artifact_count', 2),
    'idempotency_key', 'annual-close-facts-approved-1'
  )
);

select public.record_corporate_document_event(
  jsonb_build_object(
    'decision_id', '41111111-1111-4111-8111-111111111111',
    'set_id', '42111111-1111-4111-8111-111111111111',
    'event_kind', 'signing_requested',
    'decision_hash', 'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923',
    'metadata', '{}'::jsonb,
    'idempotency_key', 'annual-close-signing-requested-1'
  )
);

select public.attest_corporate_signed_artifact(
  $json$
  {
    "decision_id": "41111111-1111-4111-8111-111111111111",
    "set_id": "42111111-1111-4111-8111-111111111111",
    "unsigned_artifact_id": "43111111-1111-4111-8111-111111111111",
    "decision_hash": "f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923",
    "signers": ["Åse Nordmann", "Jørgen Østby"],
    "signed_artifact": {
      "id": "47111111-1111-4111-8111-111111111111",
      "document_id": "48111111-1111-4111-8111-111111111111",
      "artifact_kind": "annual_board_minutes",
      "name": "signert-styreprotokoll-aarsregnskap.pdf",
      "content_sha256": "abababababababababababababababababababababababababababababababab",
      "byte_length": 6200,
      "mime_type": "application/pdf",
      "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/42111111-1111-4111-8111-111111111111/annual_board_minutes/abababababababababababababababababababababababababababababababab.pdf"
    },
    "idempotency_key": "annual-close-board-signed-1"
  }
  $json$::jsonb
);

select public.attest_corporate_signed_artifact(
  $json$
  {
    "decision_id": "41111111-1111-4111-8111-111111111111",
    "set_id": "42111111-1111-4111-8111-111111111111",
    "unsigned_artifact_id": "45111111-1111-4111-8111-111111111111",
    "decision_hash": "f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923",
    "signers": ["Åse Nordmann", "Jørgen Østby"],
    "signed_artifact": {
      "id": "49111111-1111-4111-8111-111111111111",
      "document_id": "50111111-1111-4111-8111-111111111111",
      "artifact_kind": "annual_general_meeting_minutes",
      "name": "signert-generalforsamlingsprotokoll-aarsregnskap.pdf",
      "content_sha256": "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
      "byte_length": 6300,
      "mime_type": "application/pdf",
      "storage_key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/2025/corporate/42111111-1111-4111-8111-111111111111/annual_general_meeting_minutes/cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd.pdf"
    },
    "idempotency_key": "annual-close-general-meeting-signed-1"
  }
  $json$::jsonb
);

select public.finalize_corporate_decision(
  jsonb_build_object(
    'decision_id', '41111111-1111-4111-8111-111111111111',
    'set_id', '42111111-1111-4111-8111-111111111111',
    'decision_hash', 'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923',
    'finalization_id', '51111111-1111-4111-8111-111111111111',
    'idempotency_key', 'annual-close-finalized-1'
  )
);

do $$
declare
  v_payload jsonb;
  v_decision_id text;
  v_set_id text;
  v_decision_hash text;
  v_finalization_id text;
  v_event_kind text;
begin
  foreach v_event_kind in array array['rejected', 'superseded']
  loop
    if v_event_kind = 'rejected' then
      v_decision_id := '61111111-1111-4111-8111-111111111111';
      v_set_id := '62111111-1111-4111-8111-111111111111';
      v_decision_hash := 'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923';
      v_finalization_id := '69111111-1111-4111-8111-111111111111';
      select payload into v_payload from annual_rehearsal_inputs;
      v_payload := replace(
        replace(
          replace(
            replace(
              replace(
                replace(
                  replace(v_payload::text,
                    '41111111-1111-4111-8111-111111111111', v_decision_id),
                  '42111111-1111-4111-8111-111111111111', v_set_id),
                '43111111-1111-4111-8111-111111111111', '63111111-1111-4111-8111-111111111111'),
              '44111111-1111-4111-8111-111111111111', '64111111-1111-4111-8111-111111111111'),
            '45111111-1111-4111-8111-111111111111', '65111111-1111-4111-8111-111111111111'),
          '46111111-1111-4111-8111-111111111111', '66111111-1111-4111-8111-111111111111'),
        'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923',
        v_decision_hash
      )::jsonb;
    else
      v_decision_id := '71111111-1111-4111-8111-111111111111';
      v_set_id := '72111111-1111-4111-8111-111111111111';
      v_decision_hash := 'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923';
      v_finalization_id := '79111111-1111-4111-8111-111111111111';
      select payload into v_payload from annual_rehearsal_inputs;
      v_payload := replace(
        replace(
          replace(
            replace(
              replace(
                replace(
                  replace(v_payload::text,
                    '41111111-1111-4111-8111-111111111111', v_decision_id),
                  '42111111-1111-4111-8111-111111111111', v_set_id),
                '43111111-1111-4111-8111-111111111111', '73111111-1111-4111-8111-111111111111'),
              '44111111-1111-4111-8111-111111111111', '74111111-1111-4111-8111-111111111111'),
            '45111111-1111-4111-8111-111111111111', '75111111-1111-4111-8111-111111111111'),
          '46111111-1111-4111-8111-111111111111', '76111111-1111-4111-8111-111111111111'),
        'f196e919acc194da43f7e4a0c7d7ec927a8b636f0bd66fe08a83b3003bddd923',
        v_decision_hash
      )::jsonb;
    end if;

    v_decision_hash := encode(
      digest(public.canonical_corporate_json_text(v_payload -> 'decision' -> 'canonical_input'), 'sha256'),
      'hex'
    );
    v_payload := jsonb_set(
      jsonb_set(v_payload, '{decision,decision_hash}', to_jsonb(v_decision_hash)),
      '{document_set,decision_hash}',
      to_jsonb(v_decision_hash)
    );

    v_payload := jsonb_set(
      v_payload,
      '{idempotency_key}',
      to_jsonb(('terminal-' || v_event_kind || '-draft')::text)
    );
    perform public.create_corporate_document_draft(v_payload);
    perform public.record_corporate_document_event(
      jsonb_build_object(
        'decision_id', v_decision_id,
        'set_id', v_set_id,
        'event_kind', 'facts_approved',
        'decision_hash', v_decision_hash,
        'metadata', jsonb_build_object('reviewed_artifact_count', 2),
        'idempotency_key', 'terminal-' || v_event_kind || '-facts-approved'
      )
    );
    perform public.record_corporate_document_event(
      jsonb_build_object(
        'decision_id', v_decision_id,
        'set_id', v_set_id,
        'event_kind', v_event_kind,
        'decision_hash', v_decision_hash,
        'metadata', jsonb_build_object('reason', 'Synthetic terminal-state rehearsal'),
        'idempotency_key', 'terminal-' || v_event_kind
      )
    );

    begin
      perform public.finalize_corporate_decision(
        jsonb_build_object(
          'decision_id', v_decision_id,
          'set_id', v_set_id,
          'decision_hash', v_decision_hash,
          'finalization_id', v_finalization_id,
          'idempotency_key', 'terminal-' || v_event_kind || '-finalization'
        )
      );
      raise exception 'expected_terminal_decision_not_raised';
    exception
      when others then
        if sqlerrm not like '%corporate_documents_terminal_decision%' then
          raise;
        end if;
    end;
  end loop;
end;
$$;

set role authenticated;
set request.jwt.claim.sub = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

do $$
begin
  if has_function_privilege('authenticated', 'public.canonical_corporate_json_text(jsonb)', 'execute')
    or has_function_privilege(
      'authenticated',
      'public.assert_corporate_decision_persisted_facts(uuid,integer,text,uuid,jsonb,text)',
      'execute'
    ) then
    raise exception 'internal_fact_validation_helpers_exposed';
  end if;
  if (select count(*) from public.corporate_decisions) <> 4 then
    raise exception 'draft_decision_count_failed';
  end if;
  if (select count(*) from public.corporate_document_artifacts where variant = 'unsigned') <> 8 then
    raise exception 'draft_artifact_count_failed';
  end if;
  if (
    select count(*)
    from public.ledger_entries
    where entry_type in ('dividend_to_owner_declared', 'dividend_to_owner_payment')
  ) <> 3 then
    raise exception 'declaration_and_payment_ledger_count_failed';
  end if;
  if (select count(*) from public.holding_actions) <> 3 then
    raise exception 'declaration_and_payment_action_count_failed';
  end if;
  if (select count(*) from public.corporate_document_events where event_kind = 'facts_approved') <> 4 then
    raise exception 'facts_approval_count_failed';
  end if;
  if (select count(*) from public.corporate_document_events where event_kind = 'signing_requested') <> 2 then
    raise exception 'signing_request_count_failed';
  end if;
  if (select count(*) from public.corporate_document_artifacts where variant = 'signed_owner_attested') <> 4 then
    raise exception 'signed_artifact_count_failed';
  end if;
  if (select count(*) from public.corporate_decision_finalizations) <> 2 then
    raise exception 'finalization_count_failed';
  end if;
  if not exists (
    select 1
    from public.corporate_decision_finalizations
    where id = '51111111-1111-4111-8111-111111111111'
      and finalization_kind = 'annual_close_adopted'
      and holding_action_id is null
      and ledger_entry_id is null
  ) then
    raise exception 'annual_close_finalization_failed';
  end if;
  if not exists (
    select 1
    from public.ledger_entries l
    where l.id = '23111111-1111-4111-8111-111111111111'
      and l.entry_type = 'dividend_to_owner_declared'
      and l.lines @> '[{"account":"2080","debit":100000.00,"credit":0}]'::jsonb
      and l.lines @> '[{"account":"2920","debit":0,"credit":100000.00}]'::jsonb
      and not l.lines @> '[{"account":"1920"}]'::jsonb
  ) then
    raise exception 'declaration_ledger_lines_failed';
  end if;
  if (
    select coalesce(sum((metadata ->> 'amount_ore')::bigint), 0)
    from public.corporate_document_events
    where decision_id = '11111111-1111-4111-8111-111111111111'
      and event_kind = 'payment_recorded'
  ) <> 10000000 then
    raise exception 'dividend_payable_not_fully_cleared';
  end if;
  if exists (
    select 1
    from public.ledger_entries l
    where l.id in (
      '26111111-1111-4111-8111-111111111111',
      '29111111-1111-4111-8111-111111111111'
    )
      and not (
        l.lines @> '[{"account":"2920"}]'::jsonb
        and l.lines @> '[{"account":"1920"}]'::jsonb
      )
  ) then
    raise exception 'payment_ledger_lines_failed';
  end if;
  if (
    select count(*)
    from public.bank_transactions
    where id in (
      '24111111-1111-4111-8111-111111111111',
      '27111111-1111-4111-8111-111111111111'
    )
      and matched_entry_id is not null
      and matched_action_id is not null
  ) <> 2 then
    raise exception 'payment_bank_match_failed';
  end if;
  begin
    update public.corporate_decisions
    set decision_hash = 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    where id = '11111111-1111-4111-8111-111111111111';
    raise exception 'expected_immutable_update_failure_not_raised';
  exception
    when others then
      if sqlerrm not like '%corporate_records_are_immutable%'
        and sqlerrm not like '%permission denied%' then
        raise;
      end if;
  end;
end;
$$;

select 'database_rehearsal_ok';
