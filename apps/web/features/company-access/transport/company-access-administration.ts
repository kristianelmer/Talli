import {
  createTalliApiClient,
  type AdministerCompanyMembershipRequest,
  type CreateCompanyInvitationRequest,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(10_000) };
}

export function listCompanyInvitations(
  accessToken: string,
  companyId: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessListInvitations(companyId, request(requestId));
}

export function createCompanyInvitation(
  accessToken: string,
  command: CreateCompanyInvitationRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessCreateInvitation(command, request(requestId));
}

export function lookupCompanyInvitation(
  accessToken: string,
  token: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessLookupInvitation({ token }, request(requestId));
}

export function acceptCompanyInvitation(
  accessToken: string,
  token: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessAcceptInvitation({ token }, request(requestId));
}

export function revokeCompanyInvitation(
  accessToken: string,
  companyId: string,
  invitationId: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessRevokeInvitation(
    invitationId,
    { companyId },
    request(requestId),
  );
}

export function resendCompanyInvitation(
  accessToken: string,
  companyId: string,
  invitationId: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessResendInvitation(
    invitationId,
    { companyId },
    request(requestId),
  );
}

export function listCompanyMemberships(
  accessToken: string,
  companyId: string,
  requestId?: string,
) {
  return client(accessToken).companyAccessListMemberships(companyId, request(requestId));
}

export function administerCompanyMembership(
  accessToken: string,
  userId: string,
  command: AdministerCompanyMembershipRequest,
  requestId?: string,
) {
  return client(accessToken).companyAccessAdministerMembership(
    userId,
    command,
    request(requestId),
  );
}
