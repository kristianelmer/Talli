export const requiredNonAffiliationCopy =
  "Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.";

export const inviteOnlyBetaCopy = "Invitasjonsbasert gratis beta";

export const preProductionDirectFilingCopy =
  "Direkte innsending åpnes først når myndighetstilgang, testmiljø og sikkerhetsgjennomgang er fullført.";

const prohibitedLaunchClaims = [
  /send inn direkte/i,
  /ferdig innsendt/i,
  /godkjent av (skatteetaten|altinn|brønnøysundregistrene|fiken)/i,
  /garantert riktig/i,
  /unngå gebyr/i,
  /ingen risiko for dagmulkt/i,
  /erstatter regnskapsfører/i,
  /alt du trenger for alle AS/i,
  /uten regnskapsfører/i,
  /menneskelig (?:kontroll|gjennomgang|kvalitetssikring)/i,
  /betaler først ved innsending/i,
  /innsendingen (?:kvalitetssikres og )?leveres til riktig myndighet/i,
  /trygg innsending/i,
];

export function validateLaunchCopy(text: string) {
  const withoutRequiredNonAffiliation = text.replace(requiredNonAffiliationCopy, "");
  const violations = prohibitedLaunchClaims
    .filter((pattern) => pattern.test(withoutRequiredNonAffiliation))
    .map((pattern) => pattern.source);

  return {
    hasRequiredNonAffiliation: text.includes(requiredNonAffiliationCopy),
    hasPreProductionGate: text.includes(preProductionDirectFilingCopy),
    violations,
    approved:
      text.includes(requiredNonAffiliationCopy) &&
      text.includes(preProductionDirectFilingCopy) &&
      violations.length === 0,
  };
}
