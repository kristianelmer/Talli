export const roles = {
  owner: "owner",
  reviewer: "reviewer",
  readonly: "readonly",
};

export function createCompanyWorkspace({ orgNumber, companyName, entityType }) {
  const isValidOrgNumber = /^\d{9}$/.test(orgNumber);
  const isSupportedEntity = entityType === "AS";
  const supportBoundary = !isValidOrgNumber
    ? {
        status: "blocked",
        code: "invalid_org_number",
        message: "Organisasjonsnummer må ha 9 sifre.",
      }
    : !isSupportedEntity
      ? {
          status: "blocked",
          code: "unsupported_entity_type",
          message: "Talli støtter kun AS i første versjon.",
        }
      : {
          status: "ready",
          code: "simple_holding_as",
          message: "Selskapet passer enkel holding AS-løypen.",
        };

  return {
    company: {
      orgNumber,
      companyName,
      entityType,
      incomeYear: 2025,
    },
    supportBoundary,
    filings: [
      { name: "aksjonærregisteroppgaven", status: "ready", issues: [] },
      { name: "årsregnskap", status: "warning", issues: ["Mangler bankutskrift for desember."] },
      { name: "skattemelding for AS", status: "draft", issues: ["Klar etter årsregnskapssimulering."] },
    ],
    workflowSteps: [
      "Selskapsoppsett",
      "Åpningsbalanse",
      "Holding actions",
      "Årsavslutning",
      "Filing preview",
    ],
    documents: [],
    reviewers: [],
    reviewComments: [],
  };
}

export function readinessSummary(workspace) {
  const blocked = workspace.filings.filter((filing) => filing.status === "blocked").length;
  const warnings = workspace.filings.filter((filing) => filing.status === "warning").length;
  const ready = workspace.filings.filter((filing) => filing.status === "ready").length;
  return { blocked, warnings, ready, total: workspace.filings.length };
}

export function attachDocument(workspace, actor, document) {
  assertCompanyAccess(workspace, actor);
  if (![roles.owner].includes(actor.role)) {
    throw new Error("Kun eier kan laste opp eller koble dokumenter.");
  }
  return {
    ...workspace,
    documents: [
      ...workspace.documents,
      {
        id: document.id,
        documentType: document.documentType,
        name: document.name,
        linkedTo: document.linkedTo,
        retentionYears: 5,
        status: document.status ?? "attached",
        storageUri: document.storageUri ?? null,
      },
    ],
  };
}

export function inviteReviewer(workspace, actor, reviewer) {
  assertCompanyAccess(workspace, actor);
  if (actor.role !== roles.owner) {
    throw new Error("Kun eier kan invitere regnskapsfører/reviewer.");
  }
  return {
    ...workspace,
    reviewers: [
      ...workspace.reviewers,
      {
        id: reviewer.id,
        name: reviewer.name,
        email: reviewer.email,
        role: roles.reviewer,
      },
    ],
  };
}

export function addReviewComment(workspace, actor, comment) {
  assertCompanyAccess(workspace, actor);
  if (![roles.owner, roles.reviewer].includes(actor.role)) {
    throw new Error("Bruker mangler tilgang til review-kommentarer.");
  }
  return {
    ...workspace,
    reviewComments: [
      ...workspace.reviewComments,
      {
        id: comment.id,
        authorId: actor.id,
        target: comment.target,
        severity: comment.severity ?? "advisory",
        body: comment.body,
        acknowledgedByOwner: false,
      },
    ],
  };
}

export function acknowledgeReviewComment(workspace, actor, commentId) {
  assertCompanyAccess(workspace, actor);
  if (actor.role !== roles.owner) {
    throw new Error("Kun eier kan akseptere åpne review-kommentarer.");
  }
  return {
    ...workspace,
    reviewComments: workspace.reviewComments.map((comment) => {
      if (comment.id !== commentId) {
        return comment;
      }
      if (comment.severity === "hard_block") {
        throw new Error("Hard systemblokk kan ikke overstyres av eier.");
      }
      return { ...comment, acknowledgedByOwner: true };
    }),
  };
}

export function assertCompanyAccess(workspace, actor) {
  if (!actor.companyOrgNumbers.includes(workspace.company.orgNumber)) {
    throw new Error("Bruker har ikke tilgang til selskapet.");
  }
}

export const demoWorkspace = attachDocument(
  addReviewComment(
    inviteReviewer(
      createCompanyWorkspace({
        orgNumber: "314259521",
        companyName: "Demo Holding AS",
        entityType: "AS",
      }),
      { id: "owner", role: roles.owner, companyOrgNumbers: ["314259521"] },
      { id: "reviewer", name: "Regnskapsfører Demo", email: "review@example.com" },
    ),
    { id: "reviewer", role: roles.reviewer, companyOrgNumbers: ["314259521"] },
    {
      id: "comment-1",
      target: "årsregnskap",
      severity: "advisory",
      body: "Bankutskrift for desember bør legges ved før filing.",
    },
  ),
  { id: "owner", role: roles.owner, companyOrgNumbers: ["314259521"] },
  {
    id: "doc-1",
    documentType: "bank_statement",
    name: "Bankutskrift desember.pdf",
    linkedTo: "årsregnskap",
    status: "missing_accepted_warning",
  },
);
