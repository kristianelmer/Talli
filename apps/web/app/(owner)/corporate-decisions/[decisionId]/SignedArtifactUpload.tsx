"use client";

import { attestSignedCorporateArtifact } from "../../../actions";
import { SubmitButton } from "../../../components/ui";

type Props = {
  decisionId: string;
  documentSetId: string;
  decisionHash: string;
  unsignedArtifactId: string;
  signedArtifactId: string;
  signedDocumentId: string;
  signers: string[];
};

export function SignedArtifactUpload(props: Props) {
  return (
    <form action={attestSignedCorporateArtifact} className="wizardForm">
      <input type="hidden" name="decisionId" value={props.decisionId} />
      <input type="hidden" name="documentSetId" value={props.documentSetId} />
      <input type="hidden" name="decisionHash" value={props.decisionHash} />
      <input type="hidden" name="unsignedArtifactId" value={props.unsignedArtifactId} />
      <input type="hidden" name="signedArtifactId" value={props.signedArtifactId} />
      <input type="hidden" name="signedDocumentId" value={props.signedDocumentId} />
      <p className="cardNote">
        Påkrevde signatarer: {props.signers.join(", ")}. Signeringen skjer utenfor Talli; last opp den
        ferdig signerte PDF-en uten å erstatte originalutkastet.
      </p>
      <label>
        Signert PDF (maks 10 MB)
        <input name="signedFile" type="file" accept="application/pdf,.pdf" required />
      </label>
      <label className="checkRow">
        <input name="ownerAttestation" type="checkbox" required />
        Jeg bekrefter at dette er en signert kopi bekreftet av eier, med alle påkrevde signatarer.
      </label>
      <SubmitButton pendingLabel="Kontrollerer og lagrer …">Bekreft signert kopi</SubmitButton>
    </form>
  );
}
