// Compute optional diagnostic headroom at the Python child launch, after UI work.
export function actualReplayEnvironment(testStarted, now = performance.now(), environment = process.env) {
  if (!environment.TALLI_RF_REPLAY_DIR) return {};
  const elapsed = now - testStarted;
  const allowance = Number.isFinite(testStarted) && Number.isFinite(now) && testStarted >= 0 && elapsed >= 0
    ? Math.max(0, Math.floor(Math.min(150_000, 360_000 - elapsed - 60_000))) : 0;
  return {
    TALLI_RF_REPLAY_DIR: environment.TALLI_RF_REPLAY_DIR,
    RUNNER_TEMP: environment.RUNNER_TEMP,
    TALLI_RF_REPLAY_EXPORT_MS: String(allowance),
  };
}
