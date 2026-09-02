"use client";

import { useState } from "react";

import { createOpeningBalanceSetup } from "../../actions";
import { Button, SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";

type ShareholderKind = "norwegian_person" | "norwegian_company";

type ShareholderRow = {
  key: string;
  name: string;
  kind: ShareholderKind;
  nationalId: string;
  orgNumber: string;
  shareCount: string;
};

type OpeningBalanceFormProps = {
  companyId: string;
  incomeYear: number;
  operationId?: string;
};

function newRow(): ShareholderRow {
  return {
    key: crypto.randomUUID(),
    name: "",
    kind: "norwegian_person",
    nationalId: "",
    orgNumber: "",
    shareCount: "",
  };
}

export function OpeningBalanceForm({
  companyId,
  incomeYear,
  operationId: initialOperationId,
}: OpeningBalanceFormProps) {
  const c = ownerCopy.onboarding.balances;
  const [bankBalance, setBankBalance] = useState("");
  const [shareCapital, setShareCapital] = useState("");
  const [shareCount, setShareCount] = useState("");
  const [nominalValue, setNominalValue] = useState("");
  const [shareholders, setShareholders] = useState<ShareholderRow[]>([newRow()]);
  const [operationId] = useState(
    () => initialOperationId ?? crypto.randomUUID(),
  );

  function updateRow(key: string, patch: Partial<ShareholderRow>) {
    setShareholders((rows) =>
      rows.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  }

  return (
    <form action={createOpeningBalanceSetup} className="wizardForm">
      <input type="hidden" name="returnTo" value="/onboarding?step=bank" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="operationId" value={operationId} />

      <label className="field">
        <span className="fieldLabel">{c.yearLabel}</span>
        <input
          name="incomeYear"
          type="number"
          inputMode="numeric"
          defaultValue={incomeYear}
          required
        />
      </label>

      <div className="fieldRow">
        <label className="field">
          <span className="fieldLabel">{c.bankLabel}</span>
          <input
            name="bankBalance"
            inputMode="decimal"
            value={bankBalance}
            onChange={(event) => setBankBalance(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="fieldLabel">{c.shareCapitalLabel}</span>
          <input
            name="shareCapital"
            inputMode="decimal"
            value={shareCapital}
            onChange={(event) => setShareCapital(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="fieldLabel">{c.shareCountLabel}</span>
          <input
            name="shareCount"
            inputMode="numeric"
            value={shareCount}
            onChange={(event) => setShareCount(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="fieldLabel">{c.nominalLabel}</span>
          <input
            name="nominalValue"
            inputMode="decimal"
            value={nominalValue}
            onChange={(event) => setNominalValue(event.target.value)}
            required
          />
        </label>
      </div>

      <div className="shareholderBlock">
        <div className="shareholderBlockHead">
          <h3 className="cardLabel">{c.shareholdersTitle}</h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShareholders((rows) => [...rows, newRow()])}
          >
            {c.addShareholder}
          </Button>
        </div>

        <div className="shareholderRows">
          {shareholders.map((row) => (
            <div className="shareholderRow" key={row.key}>
              <label className="field">
                <span className="fieldLabel">{c.nameLabel}</span>
                <input
                  name="shareholderName"
                  value={row.name}
                  onChange={(event) =>
                    updateRow(row.key, { name: event.target.value })
                  }
                  required
                />
              </label>

              <label className="field">
                <span className="fieldLabel">{c.kindLabel}</span>
                <span className="selectControl">
                  <select
                    name="shareholderKind"
                    value={row.kind}
                    onChange={(event) =>
                      updateRow(row.key, {
                        kind: event.target.value as ShareholderKind,
                      })
                    }
                  >
                    <option value="norwegian_person">{c.kindPerson}</option>
                    <option value="norwegian_company">{c.kindCompany}</option>
                  </select>
                </span>
              </label>

              <label
                className="field"
                hidden={row.kind !== "norwegian_person"}
              >
                <span className="fieldLabel">{c.nationalIdLabel}</span>
                <input
                  name="shareholderNationalId"
                  inputMode="numeric"
                  value={row.nationalId}
                  onChange={(event) =>
                    updateRow(row.key, { nationalId: event.target.value })
                  }
                />
              </label>

              <label
                className="field"
                hidden={row.kind !== "norwegian_company"}
              >
                <span className="fieldLabel">{c.orgNumberLabel}</span>
                <input
                  name="shareholderOrgNumber"
                  inputMode="numeric"
                  value={row.orgNumber}
                  onChange={(event) =>
                    updateRow(row.key, { orgNumber: event.target.value })
                  }
                />
              </label>

              <label className="field shareholderShares">
                <span className="fieldLabel">{c.sharesLabel}</span>
                <input
                  name="shareholderShareCount"
                  inputMode="numeric"
                  value={row.shareCount}
                  onChange={(event) =>
                    updateRow(row.key, { shareCount: event.target.value })
                  }
                  required
                />
              </label>

              {shareholders.length > 1 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="shareholderRemove"
                  onClick={() =>
                    setShareholders((rows) =>
                      rows.filter((item) => item.key !== row.key),
                    )
                  }
                >
                  {c.removeShareholder}
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <SubmitButton block pendingLabel={c.pending}>
        {c.cta}
      </SubmitButton>
    </form>
  );
}
