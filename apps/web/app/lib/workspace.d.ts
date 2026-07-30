export const roles: {
  owner: "owner";
  reviewer: "reviewer";
  readonly: "readonly";
};

export type Actor = {
  id: string;
  role: "owner" | "reviewer" | "readonly";
  companyOrgNumbers: string[];
};

export type FilingStatus = "ready" | "warning" | "draft" | "blocked";

export type Workspace = {
  company: {
    orgNumber: string;
    companyName: string;
    entityType: string;
    incomeYear: number;
  };
  supportBoundary: {
    status: "ready" | "blocked";
    code: string;
    message: string;
  };
  filings: Array<{
    name: string;
    status: FilingStatus;
    issues: string[];
  }>;
  workflowSteps: string[];
  documents: Array<{
    id: string;
    documentType: string;
    name: string;
    linkedTo: string;
    retentionYears: number;
    status: string;
    storageUri: string | null;
  }>;
  reviewers: Array<{
    id: string;
    name: string;
    email: string;
    role: "reviewer";
  }>;
  reviewComments: Array<{
    id: string;
    authorId: string;
    target: string;
    severity: "advisory" | "hard_block";
    body: string;
    acknowledgedByOwner: boolean;
  }>;
};

export function createCompanyWorkspace(input: {
  orgNumber: string;
  companyName: string;
  entityType: string;
}): Workspace;

export function readinessSummary(workspace: Workspace): {
  blocked: number;
  warnings: number;
  ready: number;
  total: number;
};

export function attachDocument(
  workspace: Workspace,
  actor: Actor,
  document: {
    id: string;
    documentType: string;
    name: string;
    linkedTo: string;
    status?: string;
    storageUri?: string | null;
  },
): Workspace;

export function inviteReviewer(
  workspace: Workspace,
  actor: Actor,
  reviewer: { id: string; name: string; email: string },
): Workspace;

export function addReviewComment(
  workspace: Workspace,
  actor: Actor,
  comment: {
    id: string;
    target: string;
    severity?: "advisory" | "hard_block";
    body: string;
  },
): Workspace;

export function acknowledgeReviewComment(workspace: Workspace, actor: Actor, commentId: string): Workspace;

export function assertCompanyAccess(workspace: Workspace, actor: Actor): void;

export const demoWorkspace: Workspace;
