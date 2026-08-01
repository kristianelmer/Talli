export function isLoopbackSupabaseUrl(value) {
  try {
    const hostname = new URL(value).hostname;
    return isLoopbackHostname(hostname);
  } catch {
    return false;
  }
}

export function isLoopbackPostgresUrl(value) {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "postgres:" || url.protocol === "postgresql:") &&
      isLoopbackHostname(url.hostname)
    );
  } catch {
    return false;
  }
}

function isLoopbackHostname(hostname) {
  return (
    hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]"
  );
}
