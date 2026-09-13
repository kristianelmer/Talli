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
