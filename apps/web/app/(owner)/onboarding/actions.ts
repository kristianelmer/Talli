"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  admitCompanyYearThroughApi,
  eligibilityActionErrorMessage,
  eligibilityAdmissionRestartRequired,
} from "../../../features/company-access";
import { clearEligibilityContinuation, readEligibilityContinuation } from "../../lib/eligibility-continuation";
import { currentCustomerAgreements, currentPrivacyNotice } from "../../lib/customer-agreements";
import { getCurrentSessionAccessToken } from "../../lib/supabase/auth-session";

function formString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function fail(message: string): never {
  redirect(`/onboarding?error=${encodeURIComponent(message)}`);
}

export async function admitCompanyYear(formData: FormData) {
  const continuation = await readEligibilityContinuation();
  if (!continuation) fail("Den endelige selskapsjekken er utløpt. Start sjekken på nytt.");
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) fail("Innlogging kreves.");
  if (formString(formData, "companyYearPromiseAccepted") !== "accepted") {
    fail("Du må bekrefte fullmakt, avtalene og selskapsåret.");
  }
  if (
    formString(formData, "businessTermsVersion") !== currentCustomerAgreements.businessTerms.version
    || formString(formData, "businessTermsSha256") !== currentCustomerAgreements.businessTerms.contentSha256
    || formString(formData, "dpaVersion") !== currentCustomerAgreements.dpa.version
    || formString(formData, "dpaSha256") !== currentCustomerAgreements.dpa.contentSha256
    || formString(formData, "privacyNoticeVersion") !== currentPrivacyNotice.version
    || formString(formData, "privacyNoticeSha256") !== currentPrivacyNotice.contentSha256
    || formString(formData, "capabilityManifestVersion") !== continuation.capabilityManifestVersion
    || formString(formData, "capabilityManifestSha256") !== continuation.capabilityManifestSha256
  ) {
    fail("Vilkårene eller Talli-grensen er oppdatert. Start sjekken på nytt.");
  }
  try {
    await admitCompanyYearThroughApi(accessToken, {
      operationId: randomUUID(),
      orgNumber: continuation.orgNumber,
      accountingYear: continuation.accountingYear,
      expectedPublicFactsSha256: continuation.publicFactsSha256,
      capabilityManifestVersion: continuation.capabilityManifestVersion,
      capabilityManifestSha256: continuation.capabilityManifestSha256,
      answers: continuation.answers,
      authorityAccepted: true,
      companyYearPromiseAccepted: true,
      agreementAccepted: true,
      businessTermsVersion: currentCustomerAgreements.businessTerms.version,
      businessTermsSha256: currentCustomerAgreements.businessTerms.contentSha256,
      dpaVersion: currentCustomerAgreements.dpa.version,
      dpaSha256: currentCustomerAgreements.dpa.contentSha256,
      privacyNoticeVersion: currentPrivacyNotice.version,
      privacyNoticeSha256: currentPrivacyNotice.contentSha256,
    }, randomUUID());
  } catch (error) {
    if (eligibilityAdmissionRestartRequired(error)) {
      await clearEligibilityContinuation();
    }
    fail(eligibilityActionErrorMessage(error));
  }
  await clearEligibilityContinuation();
  revalidatePath("/");
  redirect("/mfa?next=%2Fonboarding");
}
