export type CorporateArtifactKind =
  | "dividend_board_proposal"
  | "dividend_general_meeting_minutes"
  | "annual_board_minutes"
  | "annual_general_meeting_minutes";

export type CorporateDecisionInput = {
  request_id: string;
  company_id: string;
  organization_number: string;
  legal_name: string;
  income_year: number;
  decision_kind: "owner_dividend" | "annual_close";
  annual_close_source_id: string;
  source_hash: string;
  template_family: "norwegian_simple_as";
  template_version: "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1";
  annual_basis_year: number;
  financial_totals: {
    result_after_tax_ore: number;
    equity_ore: number;
    available_distribution_ore: number;
    cash_ore: number;
  };
  board_meeting: {
    meeting_date: string;
    meeting_time: string;
    place: string;
    treatment_method: "physical" | "video" | "written";
  };
  board_participants: Array<{
    participant_id: string;
    name: string;
    role: "chair" | "member";
  }>;
  general_meeting: {
    meeting_date: string;
    meeting_time: string;
    place: string;
    meeting_form: "physical" | "video";
    chair_name: string;
    co_signer_name: string;
  };
  shareholders: Array<{
    shareholder_id: string;
    name: string;
    share_count: number;
    represented_share_count: number;
    vote: "for" | "against" | "abstain";
  }>;
  total_company_shares: number;
  one_share_class_confirmed: boolean;
  dividend: {
    amount_ore: number;
    payment_date: string;
    liquidity_after_payment_ore: number;
    allocations: Array<{ shareholder_id: string; amount_ore: number }>;
  } | null;
  annual_result_allocation_ore: number;
  confirmations: {
    latest_approved_annual_accounts: boolean;
    supported_dividend_basis: boolean;
    full_board_participation: boolean;
    full_share_representation: boolean;
    unanimous_board: boolean;
    unanimous_shareholders: boolean;
    proportional_allocation: boolean;
    prudent_equity_and_liquidity: boolean;
  };
};
