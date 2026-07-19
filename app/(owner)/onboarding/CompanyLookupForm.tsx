"use client";

import { createWorkspace } from "../../actions";
import { Banner, FormField, SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

/** Step 1 — look up the company in Brønnøysund. Non-AS is blocked server-side. */
export function CompanyLookupForm() {
  const c = ownerCopy.onboarding.lookup;
  return (
    <form action={createWorkspace} className="wizardForm">
      <input type="hidden" name="returnTo" value="/onboarding" />
      <FormField
        label={c.orgLabel}
        name="orgNumber"
        inputMode="numeric"
        pattern="[0-9]{9}"
        autoComplete="off"
        required
        helper={c.orgHelp}
        validate={(value) =>
          /^\d{9}$/.test(value.trim()) ? undefined : c.orgInvalid
        }
      />
      <Banner variant="info" title={c.boundaryTitle}>
        {c.boundaryBody}
      </Banner>
      <SubmitButton block pendingLabel={c.pending}>
        {c.cta}
      </SubmitButton>
    </form>
  );
}
