export type ReviewBlockInput = {
  severity: "advisory" | "hard_block";
};

export function assertNoHardReviewBlocks(comments: ReviewBlockInput[]) {
  if (comments.some((comment) => comment.severity === "hard_block")) {
    throw new Error("Hard review-blokk må løses før simulert innsending.");
  }
}

export function assertAdvisoryCanBeAcknowledged(comment: ReviewBlockInput) {
  if (comment.severity === "hard_block") {
    throw new Error("Hard review-blokk kan ikke acknowledges som advisory.");
  }
}
