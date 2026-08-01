import type { CompanyContext } from "@talli/talli-api-client";

/**
 * Company data deliberately owned by the company-access feature at the web
 * boundary. It is a presentation model, not a Supabase persistence row.
 */
export type CompanyAccessPresentation = {
  id: string;
  org_number: string;
  name: string;
  entity_type: string;
  address: string;
  postal_code: string;
  city: string;
  status_text: string;
  source: string;
  role: "owner";
};

export function presentCompanyAccessContext(context: CompanyContext): CompanyAccessPresentation {
  return {
    id: context.id,
    org_number: context.orgNumber,
    name: context.name,
    entity_type: context.entityType,
    address: context.address,
    postal_code: context.postalCode,
    city: context.city,
    status_text: context.statusText,
    source: context.source,
    role: context.role,
  };
}
