import type { Metadata } from "next";

import { LegalPage } from "../components/LegalPage";
import { ownerCopy } from "../lib/copy";

export const metadata: Metadata = {
  title: "Vilkår – Talli",
  description: "Brukervilkår for Talli.",
};

export default function VilkarPage() {
  return <LegalPage doc={ownerCopy.legal.terms} />;
}
