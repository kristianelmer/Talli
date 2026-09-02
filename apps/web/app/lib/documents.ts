export function rf1086FeedbackFileName(contentType: string, sha256: string) {
  const extension = contentType === "application/xml" || contentType === "text/xml"
    ? "xml"
    : contentType === "application/pdf"
      ? "pdf"
      : contentType === "text/plain"
        ? "txt"
        : "bin";
  return `authority-feedback-${sha256.slice(0, 12)}.${extension}`;
}
