import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import pg from "pg";

const IDENTITY_SQL = `select pg_backend_pid() as pid, current_database() as database_name,
  d.oid as database_oid, pg_postmaster_start_time() as server_started_at,
  exists(select 1 from pg_stat_activity a where a.pid=$1 and a.datid=d.oid) as primary_present
  from pg_database d where d.datname=current_database()`;

// No target table is opened. Both activity and lock cardinalities are bounded
// inside PostgreSQL; raw query prefixes never leave the transient classifier.
export const BILLING_LOCK_SNAPSHOT_SQL = `with direct_blockers as (
  select distinct pid from unnest(pg_blocking_pids($1::integer)) as peers(pid)
  where pid<>$1::integer order by pid limit 8
), subjects as (
  select $1::integer as pid union all select pid from direct_blockers
) select a.pid, a.backend_type, a.state, a.wait_event_type,
  a.query_start, clock_timestamp() as observed_at, left(a.query,4096) as query_prefix,
  cardinality(pg_blocking_pids(a.pid)) as blocker_count,
  (pg_blocking_pids(a.pid))[1:8] as blockers,
  coalesce((select jsonb_agg(to_jsonb(chosen)) from (
    select l.locktype, l.mode, l.granted, l.database, l.relation, l.transactionid,
      n.nspname as schema_name, c.relname as relation_name
    from pg_locks l left join pg_class c on c.oid=l.relation
      left join pg_namespace n on n.oid=c.relnamespace
    where l.pid=a.pid order by l.granted, l.locktype, l.relation limit 8
  ) chosen),'[]'::jsonb) as locks
  from pg_stat_activity a join subjects s using(pid) order by a.pid limit 9`;

const label = (value, allowed) => typeof value === "string" && allowed.includes(value)
  ? value : "unclassified";
const integer = value => Number.isInteger(value) && value > 0 && value <= 4_294_967_295
  ? value : null;
const instant = value => {
  if (!(value instanceof Date) && (typeof value !== "string" || value.length > 40)) return null;
  const date = new Date(value);
  return Number.isFinite(date.valueOf()) ? date.toISOString() : null;
};
const relations = [
  "billing.annual_checkout_observation_principals", "billing.annual_checkout_observation_authorities",
  "backend_system.annual_checkout_observation_work", "billing.annual_purchases", "billing.annual_operations",
  "billing_annual_retired.annual_checkout_observation_principals",
  "billing_annual_retired.annual_checkout_observation_authorities",
];

export function summarizeBillingLockRows(rows) {
  if (!Array.isArray(rows) || rows.length > 9) throw new Error("billing_deadlock_metadata_unavailable");
  return rows.map(row => {
    if (!row || typeof row !== "object" || !Array.isArray(row.locks) || row.locks.length > 8
        || !Array.isArray(row.blockers) || row.blockers.length > 8
        || row.locks.some(lock => !lock || typeof lock !== "object")) {
      throw new Error("billing_deadlock_metadata_unavailable");
    }
    const query = typeof row.query_prefix === "string" ? row.query_prefix : "";
    if (query.length > 4096) throw new Error("billing_deadlock_metadata_unavailable");
    const command = query.replace(/^(?:\s|--[^\n]*\n)*/, "").match(/^[A-Za-z]+/)?.[0]?.toUpperCase();
    return {
      pid: integer(row.pid),
      backendType: label(row.backend_type, ["client backend", "autovacuum worker", "background worker",
        "logical replication worker", "parallel worker"]),
      state: label(row.state, ["active", "idle", "idle in transaction", "idle in transaction (aborted)"]),
      waitType: label(row.wait_event_type, ["Lock", "IO", "Client", "Activity", "IPC", "Timeout", "LWLock"]),
      queryStartedAt: instant(row.query_start), observedAt: instant(row.observed_at),
      queryCommand: label(command, ["SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "BEGIN", "COMMIT", "ROLLBACK", "VACUUM", "ANALYZE"]),
      queryPrefixSha256: createHash("sha256").update(query).digest("hex"),
      queryPrefixCharacters: query.length,
      catalogReaders: ["pg_get_viewdef", "pg_get_constraintdef", "pg_get_indexdef", "pg_get_expr"]
        .filter(name => query.includes(name)),
      blockerCount: integer(row.blocker_count) ?? 0,
      blockers: row.blockers.map(integer).filter(value => value !== null),
      locks: row.locks.map(lock => ({
        type: label(lock.locktype, ["relation", "transactionid", "virtualxid", "tuple", "object", "advisory"]),
        mode: label(lock.mode, ["AccessShareLock", "RowShareLock", "RowExclusiveLock", "ShareUpdateExclusiveLock",
          "ShareLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"]),
        granted: lock.granted === true,
        databaseOid: integer(lock.database), relationOid: integer(lock.relation),
        transactionId: typeof lock.transactionid === "string" && /^\d{1,10}$/.test(lock.transactionid)
          ? lock.transactionid : null,
        relation: label(typeof lock.schema_name === "string" && typeof lock.relation_name === "string"
          ? `${lock.schema_name}.${lock.relation_name}` : null, relations),
      })),
    };
  });
}

function localTarget(primary, databaseUrl) {
  try {
    const url = new URL(databaseUrl);
    const host = url.hostname.replace(/^\[|\]$/g, "");
    const parameters = primary.connectionParameters;
    if (!["postgres:", "postgresql:"].includes(url.protocol) || url.search || url.hash
        || !["127.0.0.1", "localhost", "::1"].includes(host) || url.pathname !== "/postgres"
        || parameters.host !== host || Number(parameters.port) !== Number(url.port || 5432)
        || parameters.database !== "postgres" || !integer(primary.processID)) throw new Error();
    return url.toString();
  } catch {
    throw new Error("billing_deadlock_diagnostic_requires_same_disposable_loopback_target");
  }
}

export async function runBillingObservationReapply(primary, databaseUrl, observationSql,
  observerFactory = configuration => new pg.Client(configuration)) {
  const connectionString = localTarget(primary, databaseUrl);
  let observer, monitor, wake, timer, stopped = false, unavailable = false;
  let result, primaryFailure, primaryFailed = false, cleanupFailure = false;
  const snapshots = [], signatures = new Set();
  const started = performance.now();
  let closing;
  const closeObserver = () => closing ??= (async () => {
    if (!observer) return;
    let closeTimer;
    try {
      await Promise.race([observer.end(), new Promise((_, reject) => {
        closeTimer = setTimeout(() => reject(new Error("billing_deadlock_observer_close_timeout")), 1000);
      })]);
    } catch {
      cleanupFailure = true;
      // Only this invocation's independent observer transport is disconnected.
      try { observer.connection?.stream?.destroy(); }
      catch { /* Closure remains unproved; successful primary cannot pass. */ }
    } finally { clearTimeout(closeTimer); }
  })();
  try {
    try {
      observer = observerFactory({ connectionString, connectionTimeoutMillis: 1000,
        query_timeout: 500, statement_timeout: 250, lock_timeout: 100,
        application_name: "talli_billing_deadlock_diagnostic" });
      if (observer === primary || observer.connection?.stream === primary.connection.stream) {
        observer = undefined;
        throw new Error("billing_deadlock_observer_must_be_independent");
      }
      observer.on("error", () => { unavailable = true; });
      await observer.connect();
      const identity = await observer.query(IDENTITY_SQL, [primary.processID]);
      const row = identity.rows[0];
      if (identity.rows.length !== 1 || !row?.primary_present || row.database_name !== "postgres"
          || !integer(row.database_oid) || !instant(row.server_started_at)
          || !integer(row.pid) || row.pid === primary.processID
          || observer.connection.stream.remoteAddress !== primary.connection.stream.remoteAddress
          || observer.connection.stream.remotePort !== primary.connection.stream.remotePort) {
        throw new Error("billing_deadlock_observer_identity_unavailable");
      }
      monitor = (async () => {
        try {
          for (let samples = 0; !stopped && samples < 60; samples += 1) {
            const remaining = Math.floor(6000 - (performance.now() - started));
            if (remaining <= 0) break;
            try {
              const acquiredBeforeSettlement = !stopped;
              const captured = await observer.query({ text: BILLING_LOCK_SNAPSHOT_SQL,
                values: [primary.processID], query_timeout: Math.min(500, remaining) });
              const rows = summarizeBillingLockRows(captured.rows);
              if (rows.some(value => value.pid === primary.processID && value.waitType === "Lock")) {
                const signature = JSON.stringify(rows.map(({ observedAt, ...value }) => value));
                if (!signatures.has(signature) && snapshots.length < 16) {
                  const snapshot = { acquiredBeforeSettlement, completedBeforeSettlement: !stopped, rows };
                  if (Buffer.byteLength(JSON.stringify([...snapshots, snapshot])) <= 60_000) {
                    signatures.add(signature); snapshots.push(snapshot);
                  }
                }
              }
            } catch { unavailable = true; break; }
            if (!stopped) await new Promise(resolve => {
              wake = resolve; timer = setTimeout(resolve, Math.min(100,
                Math.max(0, 6000 - (performance.now() - started))));
            });
          }
        } finally { await closeObserver(); }
      })();
    } catch { unavailable = true; await closeObserver(); }
    try { result = await primary.query(observationSql); }
    catch (error) { primaryFailed = true; primaryFailure = error; }
  } finally {
    stopped = true;
    clearTimeout(timer); wake?.();
    await monitor;
    await closeObserver();
  }
  if (primaryFailure?.code === "40P01") {
    console.error("billing_checkout_deadlock_diagnostic " + JSON.stringify({
      stage: "observation-reapply", unavailable, cleanupFailure, snapshots,
      qualification: "sampled-lock-metadata-only-no-causefix",
    }));
  }
  if (primaryFailed) throw primaryFailure;
  if (cleanupFailure) throw new Error("billing_deadlock_observer_cleanup_unavailable");
  return result;
}
