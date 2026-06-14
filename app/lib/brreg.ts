export type BrregAddress = {
  adresse?: string[];
  postnummer?: string;
  poststed?: string;
};

export type BrregEntityPayload = {
  organisasjonsnummer: string;
  navn: string;
  organisasjonsform?: {
    kode?: string;
    beskrivelse?: string;
  };
  forretningsadresse?: BrregAddress;
  postadresse?: BrregAddress;
  underAvvikling?: boolean;
  underKonkursbehandling?: boolean;
  slettedato?: string;
};

export type BrregCompanyIdentity = {
  orgNumber: string;
  name: string;
  entityType: string;
  address: string;
  postalCode: string;
  city: string;
  statusText: string;
  source: "brreg";
};

export function mapBrregEntity(payload: BrregEntityPayload): BrregCompanyIdentity {
  const address = payload.forretningsadresse ?? payload.postadresse ?? {};
  const statusText = payload.slettedato
    ? "slettet"
    : payload.underKonkursbehandling
      ? "under konkursbehandling"
      : payload.underAvvikling
        ? "under avvikling"
        : "aktiv";

  return {
    orgNumber: payload.organisasjonsnummer,
    name: payload.navn,
    entityType: payload.organisasjonsform?.kode ?? "",
    address: (address.adresse ?? []).join(", "),
    postalCode: address.postnummer ?? "",
    city: address.poststed ?? "",
    statusText,
    source: "brreg",
  };
}

export async function fetchBrregEntity(orgNumber: string, fetcher: typeof fetch = fetch) {
  if (!/^\d{9}$/.test(orgNumber)) {
    throw new Error("Organisasjonsnummer må ha 9 sifre.");
  }
  const response = await fetcher(`https://data.brreg.no/enhetsregisteret/api/enheter/${orgNumber}`, {
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (response.status === 404) {
    throw new Error("Fant ikke organisasjonsnummeret i Enhetsregisteret.");
  }
  if (!response.ok) {
    throw new Error("Kunne ikke hente selskapsdata fra Brønnøysundregistrene.");
  }
  return mapBrregEntity((await response.json()) as BrregEntityPayload);
}
