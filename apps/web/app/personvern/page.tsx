import type { Metadata } from "next";

import { LegalPage } from "../components/LegalPage";
import { ownerCopy } from "../lib/copy";

export const metadata: Metadata = {
  title: "Personvern – Talli",
  description:
    "Slik behandler Talli personopplysninger når du bruker tjenesten på talli.no.",
  alternates: { canonical: "/personvern" },
};

export default function PersonvernPage() {
  return <LegalPage doc={ownerCopy.legal.privacy} />;
}
