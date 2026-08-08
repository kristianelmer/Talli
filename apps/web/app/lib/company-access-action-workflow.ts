export type InvitationCommandName =
  | "create_invitation"
  | "accept_invitation"
  | "revoke_invitation"
  | "resend_invitation";

type CreateCommand = {
  operationId: string;
  companyId: string;
  invitedEmail: string;
  role: "reviewer" | "read_only";
};

type AcceptCommand = { operationId: string; token: string };
type MutationCommand = {
  operationId: string;
  companyId: string;
  invitationId: string;
  expectedUpdatedAt: string;
};

export type InvitationCommandByName = {
  create_invitation: CreateCommand;
  accept_invitation: AcceptCommand;
  revoke_invitation: MutationCommand;
  resend_invitation: MutationCommand;
};

type Invitation = {
  id: string;
  companyId: string;
  invitedEmail: string;
  role: "reviewer" | "read_only";
  status: string;
};

type Membership = {
  companyId: string;
  role: "reviewer" | "read_only";
};

export type InvitationSideEffectContinuation = {
  operationId: string;
  commandName: InvitationCommandName;
  companyId: string;
  invitation?: Invitation;
  membership?: Membership;
  deliveryToken?: string | null;
  deliverySubject?: string | null;
  deliveryBody?: string | null;
};

export type CompanyAccessActionWorkflowDependencies = {
  create(command: CreateCommand): Promise<InvitationSideEffectContinuation>;
  accept(command: AcceptCommand): Promise<InvitationSideEffectContinuation>;
  revoke(command: MutationCommand): Promise<InvitationSideEffectContinuation>;
  resend(command: MutationCommand): Promise<InvitationSideEffectContinuation>;
  listPending(actorId: string): Promise<InvitationSideEffectContinuation[]>;
  persistOutbox(input: {
    actorId: string;
    operationId: string;
    commandName: "create_invitation" | "resend_invitation";
    companyId: string;
    recipientEmail: string;
    invitationId: string;
    role: "reviewer" | "read_only";
    deliveryToken: string;
    deliverySubject: string;
    deliveryBody: string;
  }): Promise<void>;
  persistAudit(input: {
    actorId: string;
    operationId: string;
    commandName: InvitationCommandName;
    companyId: string;
    role: "reviewer" | "read_only";
  }): Promise<void>;
  complete(operationId: string): Promise<void>;
};

export class InvitationContinuationPendingError extends Error {
  constructor() {
    super("Invitation side-effect continuation pending.");
    this.name = "InvitationContinuationPendingError";
  }
}

function requiredInvitation(
  continuation: InvitationSideEffectContinuation,
): Invitation {
  if (!continuation.invitation) throw new InvitationContinuationPendingError();
  return continuation.invitation;
}

function roleFor(continuation: InvitationSideEffectContinuation) {
  const role = continuation.invitation?.role ?? continuation.membership?.role;
  if (role !== "reviewer" && role !== "read_only") {
    throw new InvitationContinuationPendingError();
  }
  return role;
}

export function createCompanyAccessActionWorkflow(
  dependencies: CompanyAccessActionWorkflowDependencies,
) {
  async function finish(actorId: string, continuation: InvitationSideEffectContinuation) {
    try {
      if (continuation.commandName === "create_invitation" || continuation.commandName === "resend_invitation") {
        const invitation = requiredInvitation(continuation);
        if (continuation.deliveryToken && (!continuation.deliverySubject || !continuation.deliveryBody)) {
          throw new InvitationContinuationPendingError();
        }
        if (continuation.deliveryToken) {
          await dependencies.persistOutbox({
            actorId,
            operationId: continuation.operationId,
            commandName: continuation.commandName,
            companyId: continuation.companyId,
            recipientEmail: invitation.invitedEmail,
            invitationId: invitation.id,
            role: invitation.role,
            deliveryToken: continuation.deliveryToken,
            deliverySubject: continuation.deliverySubject!,
            deliveryBody: continuation.deliveryBody!,
          });
        }
      }
      await dependencies.persistAudit({
        actorId,
        operationId: continuation.operationId,
        commandName: continuation.commandName,
        companyId: continuation.companyId,
        role: roleFor(continuation),
      });
      await dependencies.complete(continuation.operationId);
    } catch (error) {
      if (error instanceof InvitationContinuationPendingError) throw error;
      throw new InvitationContinuationPendingError();
    }
  }

  return {
    async execute<Name extends InvitationCommandName>(
      actorId: string,
      commandName: Name,
      command: InvitationCommandByName[Name],
    ) {
      const executor = dependencies[commandName === "create_invitation"
        ? "create"
        : commandName === "accept_invitation"
          ? "accept"
          : commandName === "revoke_invitation"
            ? "revoke"
            : "resend"] as (
        value: InvitationCommandByName[Name],
      ) => Promise<InvitationSideEffectContinuation>;
      const continuation = await executor(command);
      if (continuation.operationId !== command.operationId || continuation.commandName !== commandName) {
        throw new InvitationContinuationPendingError();
      }
      await finish(actorId, continuation);
      return continuation;
    },
    async recover(actorId: string) {
      const continuations = await dependencies.listPending(actorId);
      if (continuations.length > 20) throw new InvitationContinuationPendingError();
      for (const continuation of continuations) await finish(actorId, continuation);
      return continuations.length;
    },
  };
}
