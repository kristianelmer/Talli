type Rf1086ProductionScope = {
  companyId: string;
  userId: string;
  incomeYear: number;
  obligation: string;
  caseProfile: string;
  environment: string;
};

type ScopedProductionSubmission = {
  id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: string;
  case_profile: string;
  environment: string;
  created_at: string;
  updated_at: string;
};

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export function selectLatestRf1086ProductionSubmission<T extends ScopedProductionSubmission>(
  submissions: readonly T[],
  scope: Rf1086ProductionScope,
): T | null {
  const exact = submissions.filter(
    (submission) => submission.company_id === scope.companyId
      && submission.user_id === scope.userId
      && submission.income_year === scope.incomeYear
      && submission.obligation === scope.obligation
      && submission.case_profile === scope.caseProfile
      && submission.environment === scope.environment,
  );

  exact.sort((left, right) =>
    timestamp(right.updated_at) - timestamp(left.updated_at)
      || timestamp(right.created_at) - timestamp(left.created_at)
      || right.id.localeCompare(left.id),
  );
  return exact[0] ?? null;
}
