import {
  refreshSystemUserRequestAction,
  startSystemUserRequestAction,
} from "../../actions";
import { LinkButton, SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import type { SystemUserRequestPresentation } from "./_presentation";

type SystemUserRequestControlsProps = {
  companyId: string;
  request: SystemUserRequestPresentation | null;
};

export function SystemUserRequestControls({
  companyId,
  request,
}: SystemUserRequestControlsProps) {
  const c = ownerCopy.connections.actions;
  const actions = request?.actions ?? [];
  const canCreate = request === null || actions.includes("create");

  return (
    <div className="filingConfirmForm" aria-label={ownerCopy.connections.actionsLabel}>
      {canCreate ? (
        <form action={startSystemUserRequestAction}>
          <input type="hidden" name="companyId" value={companyId} />
          <SubmitButton pendingLabel={request ? c.createNewPending : c.createPending}>
            {request ? c.createNew : c.create}
          </SubmitButton>
        </form>
      ) : null}

      {actions.includes("continue") && request?.continueHref ? (
        <LinkButton variant="primary" href={request.continueHref}>
          {c.continue}
        </LinkButton>
      ) : null}

      {actions.includes("refresh") && request ? (
        <form action={refreshSystemUserRequestAction}>
          <input type="hidden" name="companyId" value={companyId} />
          <input type="hidden" name="requestId" value={request.requestId} />
          <SubmitButton variant="secondary" pendingLabel={c.refreshPending}>
            {c.refresh}
          </SubmitButton>
        </form>
      ) : null}

      {actions.includes("retry_verification") && request ? (
        <form action={refreshSystemUserRequestAction}>
          <input type="hidden" name="companyId" value={companyId} />
          <input type="hidden" name="requestId" value={request.requestId} />
          <SubmitButton variant="secondary" pendingLabel={c.retryVerificationPending}>
            {c.retryVerification}
          </SubmitButton>
        </form>
      ) : null}
    </div>
  );
}
