export type PersistedCorporateDocumentArtifact = {
  documentId: string;
};

export async function persistAndRegisterCorporateDocumentDraft<
  Artifact extends PersistedCorporateDocumentArtifact,
>(input: {
  persist: () => Promise<{ artifacts: Artifact[] }>;
  register: (artifacts: Artifact[]) => Promise<void>;
  remove: (artifact: Artifact) => Promise<void>;
}): Promise<{ artifacts: Artifact[] }> {
  let persisted: { artifacts: Artifact[] } | undefined;
  try {
    persisted = await input.persist();
    await input.register(persisted.artifacts);
    return persisted;
  } catch (error) {
    if (!persisted) throw error;
    const cleanup = await Promise.allSettled(
      persisted.artifacts.map((artifact) => input.remove(artifact)),
    );
    const cleanupFailures = cleanup
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => result.reason);
    if (cleanupFailures.length > 0) {
      throw new AggregateError(
        [error, ...cleanupFailures],
        "Dokumentregistreringen feilet, og nye PDF-objekter kunne ikke ryddes opp.",
      );
    }
    throw error;
  }
}
