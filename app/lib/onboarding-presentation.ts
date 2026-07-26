export type OnboardingPhase = "lookup" | "balances" | "bank";

type OnboardingPresentationInput = {
  hasCompany: boolean;
  hasSetup: boolean;
  hasError: boolean;
  step?: string;
};

export function shouldRedirectReturningOwner(input: OnboardingPresentationInput) {
  return !input.hasError && input.hasSetup && input.step !== "bank";
}

export function selectOnboardingPhase(input: OnboardingPresentationInput): OnboardingPhase {
  if (input.hasError && input.hasSetup && input.step !== "bank") return "lookup";
  if (!input.hasCompany) return "lookup";
  if (!input.hasSetup) return "balances";
  return "bank";
}
