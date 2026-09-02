"use client";

import { useState } from "react";

import { recordSharePurchase } from "../../../actions";
import { SubmitButton } from "../../../components/ui";
import { ownerCopy } from "../../../lib/copy";
import {
  InvestmentEvidenceFields,
  investmentEvidenceComplete,
  type InvestmentEvidenceOption,
  type InvestmentEvidenceState,
} from "./InvestmentEvidenceFields";
import { SelectField, TextField } from "./fields";

type Props = {
  companyId: string;
  incomeYear: number;
  operationId?: string;
  bankTransactions: InvestmentEvidenceOption[];
  documents: InvestmentEvidenceOption[];
};

export function SharePurchaseWizard({
  companyId,
  incomeYear,
  operationId: initialOperationId,
  bankTransactions,
  documents,
}: Props) {
  const a = ownerCopy.actions;
  const c = a.sharePurchase;
  const [investmentName, setInvestmentName] = useState("");
  const [investmentKey, setInvestmentKey] = useState("");
  const [orgNumber, setOrgNumber] = useState("");
  const [kind, setKind] = useState("norwegian_private_company");
  const [classification, setClassification] = useState("other_long_term");
  const [treatment, setTreatment] = useState("fritaksmetoden");
  const [acquisitionDate, setAcquisitionDate] = useState("");
  const [shareCount, setShareCount] = useState("");
  const [purchaseAmount, setPurchaseAmount] = useState("");
  const [transactionCosts, setTransactionCosts] = useState("0");
  const [fundEquityRatio, setFundEquityRatio] = useState("");
  const [fundStatement, setFundStatement] = useState("");
  const [boundaryConfirmed, setBoundaryConfirmed] = useState(false);
  const [evidence, setEvidence] = useState<InvestmentEvidenceState>({
    mode: "manual_fallback",
    bankTransactionId: "",
    documentId: "",
    reference: "",
    ownerAttested: false,
  });
  const [operationId] = useState(() => initialOperationId ?? crypto.randomUUID());

  const ready =
    investmentName.trim() !== "" &&
    (kind === "norwegian_private_company" || investmentKey.trim() !== "") &&
    acquisitionDate.trim() !== "" &&
    shareCount.trim() !== "" &&
    purchaseAmount.trim() !== "" &&
    investmentEvidenceComplete(evidence) &&
    boundaryConfirmed &&
    (kind !== "norwegian_private_company" || /^\d{9}$/.test(orgNumber)) &&
    (kind !== "norwegian_equity_fund"
      || (fundEquityRatio.trim() !== "" && fundStatement.trim() !== ""));

  function changeKind(value: string) {
    setKind(value);
    setClassification(
      value === "norwegian_equity_fund"
        ? "current_fund"
        : value === "norwegian_listed_share"
          ? "current_listed_share"
          : "other_long_term",
    );
  }

  return (
    <form action={recordSharePurchase} className="wizardForm">
      <input type="hidden" name="operationId" value={operationId} />
      <input type="hidden" name="returnTo" value="/actions" />
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />

      <TextField
        label={c.nameLabel}
        name="investmentName"
        value={investmentName}
        onChange={setInvestmentName}
        required
      />
      <div className="fieldRow">
        {kind === "norwegian_private_company" ? null : (
          <TextField
            label="ISIN"
            name="investmentKey"
            value={investmentKey}
            onChange={setInvestmentKey}
            helper="12 tegn og starter med NO."
            required
          />
        )}
        <TextField
          label={c.orgLabel}
          name="orgNumber"
          value={orgNumber}
          onChange={setOrgNumber}
          inputMode="numeric"
        />
      </div>
      <div className="fieldRow">
        <SelectField
          label={a.investmentKind.label}
          name="investmentKind"
          value={kind}
          onChange={changeKind}
          required
        >
          <option value="norwegian_private_company">
            {a.investmentKind.norwegianPrivate}
          </option>
          <option value="norwegian_listed_share">Norsk børsnotert aksje (NOK)</option>
          <option value="norwegian_equity_fund">Norsk aksje- eller kombinasjonsfond (NOK)</option>
        </SelectField>
        <SelectField
          label={a.taxTreatment.label}
          name="taxTreatment"
          value={treatment}
          onChange={setTreatment}
          required
        >
          <option value="fritaksmetoden">{a.taxTreatment.fritak}</option>
        </SelectField>
      </div>
      <SelectField
        label="Regnskapsklassifisering"
        name="accountingClassification"
        value={classification}
        onChange={setClassification}
        required
      >
        {kind === "norwegian_private_company" ? (
          <>
            <option value="other_long_term">Andre langsiktige investeringer</option>
            <option value="associate">Tilknyttet selskap</option>
            <option value="subsidiary">Datterselskap</option>
          </>
        ) : kind === "norwegian_listed_share" ? (
          <option value="current_listed_share">Markedsbasert aksje</option>
        ) : (
          <option value="current_fund">Markedsbasert fond</option>
        )}
      </SelectField>
      <div className="fieldRow">
        <TextField
          label={c.dateLabel}
          name="acquisitionDate"
          value={acquisitionDate}
          onChange={setAcquisitionDate}
          placeholder="2025-01-01"
          helper={a.dateHelp}
          required
        />
        <TextField
          label={c.sharesLabel}
          name="shareCount"
          value={shareCount}
          onChange={setShareCount}
          inputMode="decimal"
          required
        />
      </div>
      <div className="fieldRow">
        <TextField
          label={c.amountLabel}
          name="purchaseAmount"
          value={purchaseAmount}
          onChange={setPurchaseAmount}
          inputMode="decimal"
          required
        />
        <input type="hidden" name="documentStatus" value="not_required" />
        <TextField
          label="Transaksjonskostnader (kr)"
          name="transactionCosts"
          value={transactionCosts}
          onChange={setTransactionCosts}
          inputMode="decimal"
          required
        />
      </div>

      {kind === "norwegian_equity_fund" ? (
        <div className="fieldRow">
          <TextField
            label="Aksjeandel ved kjøp (basispoeng)"
            name="fundEquityRatioBasisPoints"
            value={fundEquityRatio}
            onChange={setFundEquityRatio}
            inputMode="numeric"
            helper="0–10 000. Bruk verdien fra fondets skatteoppgave."
            required
          />
          <TextField
            label="Referanse til fondets skatteoppgave"
            name="fundTaxStatementReference"
            value={fundStatement}
            onChange={setFundStatement}
            required
          />
        </div>
      ) : null}
      <label className="checkboxRow">
        <input
          type="checkbox"
          name="investmentBoundaryConfirmed"
          value="true"
          checked={boundaryConfirmed}
          onChange={(event) => setBoundaryConfirmed(event.target.checked)}
          required
        />
        <span>
          {kind === "norwegian_private_company"
            ? "Jeg bekrefter at dette er en enkelt ordinær aksjeklasse med like rettigheter, uten uvanlige særrettigheter, og at handelen er begrenset og ikke aktiv virksomhet."
            : "Jeg bekrefter at handelen er begrenset og ikke aktiv handelsvirksomhet."}
        </span>
      </label>
      <InvestmentEvidenceFields
        documents={documents}
        state={evidence}
        onChange={setEvidence}
      />

      <SubmitButton disabled={!ready} pendingLabel={a.pending}>
        {a.confirmCta}
      </SubmitButton>
    </form>
  );
}
