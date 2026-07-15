"use client";

import { removeUnlinkedDocument } from "../../actions";
import { SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

const c = ownerCopy.documents.list;

export function DocumentRemovalButton({ documentId }: { documentId: string }) {
  return (
    <form
      action={removeUnlinkedDocument}
      onSubmit={(event) => {
        if (!window.confirm(c.removeConfirm)) event.preventDefault();
      }}
    >
      <input type="hidden" name="returnTo" value="/documents" />
      <input type="hidden" name="documentId" value={documentId} />
      <SubmitButton variant="destructive" size="sm" pendingLabel={c.removing}>
        {c.remove}
      </SubmitButton>
    </form>
  );
}
