import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { cpSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { checkArchitecture } from "../scripts/check-architecture.mjs";

const root=fileURLToPath(new URL("..",import.meta.url));
test("preserved Tax retirement requires exact artifact bytes, source restoration and exclusive ownership", () => {
  const directory=mkdtempSync(join(tmpdir(),"talli-tax-architecture-"));
  for (const name of ["architecture","supabase"]) cpSync(join(root,name),join(directory,name),{recursive:true});
  symlinkSync(join(root,"apps"),join(directory,"apps"),"dir");
  const catalogPath=join(directory,"architecture/database-catalog.json");
  const catalog=JSON.parse(readFileSync(catalogPath,"utf8"));
  const retirement=catalog.preservedSourceRetirements[0];
  const rollback=retirement.artifacts.rollback;
  const path=join(directory,rollback.path);
  const original=readFileSync(path,"utf8");
  const errors=()=>checkArchitecture({root:directory,writeEvidence:false}).errors.join("\n");
  const invalid=/preserved source retirement is not bound/u;
  try {
    assert.doesNotMatch(errors(),invalid);
    const deferredProbe = join(directory,"supabase/contract-migrations/uncatalogued_probe.sql");
    writeFileSync(deferredProbe,"create table company_tax_filing.uncatalogued_probe(id uuid);\n");
    assert.match(errors(), /migration table missing from catalog company_tax_filing\.uncatalogued_probe/u);
    rmSync(deferredProbe);
    writeFileSync(path,original+"\n-- unbound edit\n");
    assert.match(errors(),invalid);
    const withoutCopy=original.replace("insert into public.holding_actions select * from company_tax_filing.settlements;", "perform 1;");
    writeFileSync(path,withoutCopy);
    rollback.sha256=createHash("sha256").update(withoutCopy).digest("hex");
    writeFileSync(catalogPath,JSON.stringify(catalog));
    assert.match(errors(),invalid);
    writeFileSync(path,original);
    rollback.sha256=createHash("sha256").update(original).digest("hex");
    catalog.tables.find(item=>item.name===retirement.successor).owner="backend:annual_compliance";
    writeFileSync(catalogPath,JSON.stringify(catalog));
    assert.match(errors(),invalid);
  } finally {rmSync(directory,{recursive:true,force:true});}
});

test("#152 mixed actions retain exact Accounts/Audit chains and cannot inherit permission for another edit", async () => {
  const { execFileSync } = await import("node:child_process");
  const { validateCompatibilityRegistry } = await import("../scripts/check-architecture.mjs");
  const directory = mkdtempSync(join(tmpdir(), "talli-tax-composition-"));
  const baselinePath = join(root, "architecture/compatibility-baseline.json");
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const registry = JSON.parse(readFileSync(join(root, "architecture/compatibility.json"), "utf8"));
  const source = readFileSync(join(root, "apps/web/app/actions.ts"), "utf8");
  const originals = new Map();
  const sourceAtRevision = (path) => {
    if (!originals.has(path)) {
      try { originals.set(path, execFileSync("git", ["show", `${baseline.sourceRevision}:${path}`], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })); }
      catch { originals.set(path, undefined); }
    }
    return originals.get(path);
  };
  const gateSources = new Map();
  const sourceAtGateRevision = (revision, path) => {
    const key = `${revision}:${path}`;
    if (!gateSources.has(key)) {
      try { gateSources.set(key, execFileSync("git", ["show", key], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })); }
      catch { gateSources.set(key, undefined); }
    }
    return gateSources.get(key);
  };
  const catalog = JSON.parse(readFileSync(join(root, "architecture/database-catalog.json"), "utf8"));
  const owners = new Map(catalog.tables.flatMap(row => [[`table:${row.name.replace(/^public\./u, "")}`, row.owner], ...(row.compatibilityResources ?? []).map(resource => [resource, row.owner])]));
  const operations = ["addFilingOverride", "addFilingReviewComment", "acknowledgeFilingReviewComment", "confirmAuthorityPermission", "recordAuthorityTestEvidence"];
  const check = (candidateSource = source, candidateRegistry = registry) => {
    const path = join(directory, "compatibility.json");
    writeFileSync(path, JSON.stringify(candidateRegistry));
    return validateCompatibilityRegistry(path, {
      baselinePath, sourceAtRevision, sourceAtGateRevision, resourceOwner: resource => owners.get(resource),
      currentSource: path => path === "apps/web/app/actions.ts" ? candidateSource : readFileSync(join(root, path), "utf8"),
    }).filter(error => operations.some(operation => error.endsWith(`operation:${operation}`)));
  };
  try {
    assert.deepEqual(check(), []);
    for (const operation of operations) {
      const start = source.indexOf(`export async function ${operation}(`);
      const end = source.indexOf("\nexport async function ", start + 1);
      const body = source.slice(start, end);
      for (const mutation of [
        body.replace('await supabase.from("audit_events").insert(', 'await supabase.from(dynamicAuditTable).insert('),
        body.replace('await supabase.from("audit_events").insert(', 'await supabase.from("other_events").insert('),
        body.replace('await supabase.from("audit_events").insert(', 'await supabase.from("audit_events").insert({}); await supabase.from("audit_events").insert('),
        body.replace('  revalidatePath("/");', '  await unexpectedBusinessOperation(); revalidatePath("/");'),
      ]) {
        assert.notEqual(mutation, body);
        assert.ok(check(source.slice(0, start) + mutation + source.slice(end)).some(error => error.endsWith(`operation:${operation}`)), operation);
      }
    }
    for (const [file, operation] of [
      ["apps/web/app/actions.ts", "refreshAnnualReadinessSnapshots"],
      ["apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts", "GET"],
    ]) {
      const original = readFileSync(join(root, file), "utf8");
      const readCheck = (candidate = original, candidateRegistry = registry) => {
        const path = join(directory, "compatibility.json");
        writeFileSync(path, JSON.stringify(candidateRegistry));
        return validateCompatibilityRegistry(path, {
          baselinePath, sourceAtRevision, sourceAtGateRevision, resourceOwner: resource => owners.get(resource),
          currentSource: path => path === file ? candidate : readFileSync(join(root, path), "utf8"),
        }).filter(error => error.includes(`operation:${operation}`));
      };
      assert.deepEqual(readCheck(), []);
      const start = original.indexOf(`export async function ${operation}(`);
      const head = original.slice(0, start), body = original.slice(start);
      for (const mutated of [
        body.replace('  const taxSource =', '  await supabase.from(dynamicFilingTable).select();\n  const taxSource ='),
        body.replace('  const taxSource =', '  await supabase.from("other_submissions").select();\n  const taxSource ='),
        body.replace('  const taxSource =', '  await supabase.from("filing_submissions").delete();\n  const taxSource ='),
        body.replace('  const taxSource =', '  await unexpectedBusinessOperation();\n  const taxSource ='),
      ]) {
        assert.notEqual(mutated, body);
        assert.ok(readCheck(head + mutated).length > 0, `${operation} rejects changed persistence or composition: ${mutated.slice(Math.max(0, mutated.indexOf("const taxSource") - 100), mutated.indexOf("const taxSource") + 15)}`);
      }
      const earlierRead = structuredClone(registry);
      earlierRead.migration.currentIssue = "#146";
      assert.ok(readCheck(original, earlierRead).length > 0, `${operation} requires its authorized filing stage`);
      const beforeAccounts = structuredClone(registry);
      beforeAccounts.migration.currentCapability = "company_tax_filing";
      beforeAccounts.migration.currentIssue = "#152";
      assert.ok(readCheck(original, beforeAccounts).length > 0, `${operation} cannot retire Accounts during Tax`);
      const restoredAccounts = structuredClone(registry);
      restoredAccounts.records.push(baseline.records.find(record => record.id === "compat-annual-accounts-persistence"));
      assert.ok(readCheck(original, restoredAccounts).length > 0, `${operation} requires retired Accounts facade`);
      for (const family of ["filing_previews", "filing_submissions", "filing_overrides", "filing_review_comments", "authority_permissions", "authority_test_runs"]) {
        const resource = `table:${family}`;
        const owner = owners.get(resource);
        owners.set(resource, "backend:annual_compliance");
        assert.ok(readCheck().length > 0, `${operation} requires exclusive Accounts ownership of ${family}`);
        owners.set(resource, owner);
      }
      const restoredRead = structuredClone(registry);
      restoredRead.records.push(baseline.records.find(record => record.id === "compat-company-tax-persistence"));
      assert.ok(readCheck(original, restoredRead).length > 0, `${operation} requires retired Tax facade`);
    }
    const earlier = structuredClone(registry);
    earlier.migration.currentIssue = "#146";
    assert.ok(check(source, earlier).length >= operations.length);
    const duplicateWriter = structuredClone(registry);
    duplicateWriter.records.push(baseline.records.find(record => record.id === "compat-company-tax-persistence"));
    assert.ok(check(source, duplicateWriter).length >= operations.length);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
