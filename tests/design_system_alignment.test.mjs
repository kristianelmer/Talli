import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("global tokens implement the approved crisp neutral design system", async () => {
  const [tokens, globals, layout] = await Promise.all([
    read("app/tokens.css"),
    read("app/globals.css"),
    read("app/layout.tsx"),
  ]);

  assert.match(tokens, /--color-bg:\s*#f7f8fa/iu);
  assert.match(tokens, /--color-surface:\s*#ffffff/iu);
  assert.match(tokens, /--color-border:\s*#dfe5e8/iu);
  assert.match(tokens, /--color-text:\s*#17202a/iu);
  assert.match(tokens, /--color-brand:\s*#176b55/iu);
  assert.match(tokens, /--color-warning-soft:\s*#ffffff/iu);
  assert.match(tokens, /--radius-sm:\s*6px/iu);
  assert.match(tokens, /--radius-md:\s*8px/iu);
  assert.match(tokens, /--radius-lg:\s*10px/iu);
  assert.doesNotMatch(`${tokens}\n${globals}`, /#f6f3ee|#f7f5f0|#eee9df|#ebe5da|#d8d2c7/iu);
  assert.doesNotMatch(`${tokens}\n${globals}`, /#fbf2e7|#f6ebda/iu);
  assert.doesNotMatch(globals, /linear-gradient\(/iu);
  assert.doesNotMatch(globals, /border-left(?:-width)?:\s*[2-9]px/iu);
  assert.doesNotMatch(globals, /box-shadow:\s*inset\s+[2-9]px\s+0/iu);
  assert.doesNotMatch(globals, /\.actionCard:hover\s*\{[^}]*box-shadow:\s*var\(--shadow-md\)/isu);
  assert.doesNotMatch(globals, /\.planCard--current\s*\{[^}]*box-shadow:\s*var\(--shadow-md\)/isu);
  assert.match(globals, /@media \(max-width: 560px\)[\s\S]*\.lpHeaderActions \.btn--ghost\s*\{\s*display:\s*none/iu);
  assert.doesNotMatch(layout, /next\/font|Inter\(/u);
});

test("annual workspace uses the approved flat shell without side-stripe accents", async () => {
  const styles = await read("app/components/annual-workspace/annual-workspace.module.css");

  assert.doesNotMatch(styles, /border-left:\s*[2-9]px/iu);
  assert.doesNotMatch(styles, /#fbf2e7|#f6ebda/iu);
  assert.doesNotMatch(styles, /overflow-x:\s*auto|white-space:\s*nowrap/iu);
  assert.match(styles, /\.pageHeader h1[^}]*font-size:\s*32px/isu);
});

test("authenticated navigation stays focused on the six approved destinations", async () => {
  const [nav, annualShell] = await Promise.all([
    read("app/(owner)/AppNav.tsx"),
    read("app/components/annual-workspace/AnnualWorkspaceShell.tsx"),
  ]);

  for (const href of ["/dashboard", "/actions", "/transactions", "/documents", "/connections", "/billing"]) {
    assert.ok(nav.includes(`href: "${href}"`), `missing primary navigation destination ${href}`);
  }
  for (const legacyHref of ["/year-end", "/filing", "/workspace"]) {
    assert.ok(!nav.includes(`href: "${legacyHref}"`), `legacy destination ${legacyHref} leaked into primary navigation`);
  }
  assert.doesNotMatch(nav, /items\.push\(/u);
  assert.match(nav, /data-variant="operator"/u);
  assert.match(annualShell, /aria-current="page"/u);
  assert.match(annualShell, /href="\/actions"/u);
  assert.match(annualShell, /href="\/transactions"/u);
  assert.match(annualShell, /href="\/documents"/u);
  assert.match(annualShell, /href="\/connections"/u);
  assert.match(annualShell, /href="\/billing"/u);
});

test("signed-in owners enter the annual workspace after setup and agreement acceptance", async () => {
  const [dashboard, ownerLayout] = await Promise.all([
    read("app/(owner)/dashboard/page.tsx"),
    read("app/(owner)/layout.tsx"),
  ]);

  assert.match(dashboard, /redirect\(annualOverviewHref\(/u);
  assert.match(ownerLayout, /name="returnTo"\s+type="hidden"\s+value="\/dashboard"/u);
});
