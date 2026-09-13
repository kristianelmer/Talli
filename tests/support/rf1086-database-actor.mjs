import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import pg from "pg";

const OPERATIONS = {
  claim_production_feedback_reconciliation: ["p_submission_id", "p_lease_id"],
  release_production_feedback_reconciliation: ["p_submission_id", "p_lease_id"],
  append_production_feedback_reconciliation: ["p_submission_id", "p_lease_id", "p_forsendelse_id", "p_state", "p_artifact_hashes", "p_safe_error_code", "p_correlation_id"],
};

// A disposable test login reaches only the shipped dedicated RF executor.
// Identity is independently verified by local Supabase, just as at the backend.
export async function createRfDatabaseActor(database, databaseUrl) {
  const connection = new URL(databaseUrl);
  assert.ok(["localhost", "127.0.0.1", "::1"].includes(connection.hostname));
  const role = `rf151_fixture_${randomUUID().replaceAll("-", "")}`;
  const password = randomUUID().replaceAll("-", "");
  await database.query(`create role ${role} login noinherit nobypassrls password '${password}'`);
  try { await database.query(`grant shareholder_register_filing_executor to ${role} with inherit false, set true`); }
  catch (error) { await database.query(`drop role ${role}`); throw error; }
  connection.username = role;
  connection.password = password;
  async function query(actor, statement, parameters) {
    const { data: session, error: sessionError } = await actor.auth.getSession();
    assert.ifError(sessionError);
    assert.ok(session.session?.access_token);
    const { data: identity, error: identityError } = await actor.auth.getUser(session.session.access_token);
    assert.ifError(identityError);
    assert.ok(identity.user?.id);
    const decoded = JSON.parse(Buffer.from(session.session.access_token.split(".")[1], "base64url").toString("utf8"));
    assert.equal(decoded.sub, identity.user.id);
    const { data: memberships, error: membershipError } = await actor.from("company_memberships")
      .select("company_id,role").eq("user_id", identity.user.id).not("accepted_at", "is", null);
    assert.ifError(membershipError);
    const claims = { sub: identity.user.id, role: "authenticated", email: identity.user.email,
      aal: decoded.aal === "aal2" ? "aal2" : "aal1", amr: Array.isArray(decoded.amr) ? decoded.amr : [] };
    const roles = Object.fromEntries(memberships.map(row => [row.company_id, row.role]));
    const client = new pg.Client({ connectionString: connection.href, connectionTimeoutMillis: 5_000,
      options: "-c statement_timeout=5000 -c lock_timeout=1000" });
    await client.connect();
    try {
      await client.query("begin");
      await client.query("set local role shareholder_register_filing_executor");
      await client.query(`select set_config('talli.verified_actor_id',$1,true),set_config('talli.verified_actor_claims',$2,true),
        set_config('request.jwt.claims',$2,true),set_config('talli.authorized_company_roles',$3,true)`,
      [identity.user.id, JSON.stringify(claims), JSON.stringify(roles)]);
      const result = await client.query(statement, parameters);
      await client.query("commit");
      return result;
    } catch (error) { await client.query("rollback"); throw error; }
    finally { await client.end(); }
  }
  return {
    async rpc(actor, name, parameters) {
      const keys = OPERATIONS[name];
      assert.ok(keys, "unapproved RF fixture SQL operation");
      assert.deepEqual(Object.keys(parameters).sort(), [...keys].sort());
      try {
        const result = await query(actor, `select shareholder_register_filing.${name}(${keys.map((_,i) => '$' + (i + 1)).join(',')}) as result`, keys.map(key => parameters[key]));
        return { data: result.rows[0].result, error: null };
      } catch (error) { return { data: null, error }; }
    },
    async artifact(actor, documentId) {
      try {
        const result = await query(actor, "select document_id from shareholder_register_filing.production_feedback_artifacts where document_id=$1", [documentId]);
        return { data: result.rows[0] ?? null, error: null };
      } catch (error) { return { data: null, error }; }
    },
    async close() {
      await database.query(`revoke shareholder_register_filing_executor from ${role}`);
      await database.query(`drop role ${role}`);
      assert.equal((await database.query("select count(*)::int count from pg_roles where rolname=$1", [role])).rows[0].count, 0);
    },
  };
}
