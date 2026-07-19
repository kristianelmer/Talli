import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL("../supabase/migrations/0002_fifo_investment_lots.sql", import.meta.url);

test("FIFO migration owns lot history and atomic investment writes", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create table if not exists public\.investment_lots/i);
  assert.match(sql, /create table if not exists public\.investment_lot_allocations/i);
  assert.match(sql, /lot_history_status/i);
  assert.match(sql, /create or replace function public\.record_share_purchase_fifo/i);
  assert.match(sql, /create or replace function public\.record_share_sale_fifo/i);
  assert.match(sql, /'tax_treatment', v_position\.tax_treatment/i);
  assert.match(sql, /for update/i);
  assert.match(sql, /security definer/i);
  assert.match(sql, /set search_path = public, pg_temp/i);
  assert.match(sql, /revoke insert, update, delete on public\.investment_lots from authenticated/i);
  assert.match(sql, /grant execute on function public\.record_share_sale_fifo/i);
});

test("legacy positions fail closed until lot history is reconstructed", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /default 'needs_reconstruction'/i);
  assert.match(sql, /lot_history_incomplete/i);
  assert.doesNotMatch(sql, /insert\s+into\s+public\.investment_lots\s*\([^;]+\)\s*select/i);
});
