import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("owner workflow exposes every supported event, correction, AAL2 and mobile layout", async () => {
  const [wizard, actions, route, hub, css] = await Promise.all([
    readFile(
      new URL(
        "../apps/web/app/(owner)/actions/_components/SupportedCorporateEventWizard.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8"),
    readFile(
      new URL(
        "../apps/web/app/(owner)/actions/[type]/page.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL("../apps/web/app/(owner)/actions/page.tsx", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../apps/web/app/globals.css", import.meta.url), "utf8"),
  ]);

  for (const kind of [
    "cash_capital_increase",
    "loss_coverage_capital_reduction",
    "owner_loan",
    "intercompany_loan",
    "bank_loan",
    "group_contribution",
  ])
    assert.match(wizard, new RegExp(kind, "u"));
  assert.match(wizard, /reverseSupportedCorporateEventAction/iu);
  assert.match(wizard, /correction_memo/iu);
  assert.match(
    actions,
    /recordSupportedCorporateEventAction[\s\S]+requireSensitiveActionStepUp/iu,
  );
  assert.match(
    actions,
    /reverseSupportedCorporateEventAction[\s\S]+requireSensitiveActionStepUp/iu,
  );
  assert.match(route, /SupportedCorporateEventWizard/iu);
  assert.match(hub, /"corporate-event"/u);
  assert.match(
    css,
    /@media \(max-width: 640px\)[\s\S]+\.fieldRow[\s\S]+grid-template-columns: 1fr/iu,
  );
});
