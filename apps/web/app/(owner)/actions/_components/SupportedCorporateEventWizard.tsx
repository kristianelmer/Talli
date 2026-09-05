"use client";

import { useMemo, useState } from "react";

import type {
  RecordedSupportedCorporateEventWire,
  SupportedCorporateEventKind,
  SupportedCorporateEventPhase,
  SupportedCorporateEvidenceKind,
} from "../../../../features/corporate-governance";
import {
  recordSupportedCorporateEventAction,
  reverseSupportedCorporateEventAction,
} from "../../../actions";
import { Banner, SubmitButton } from "../../../components/ui";
import { SelectField } from "./fields";

type EvidenceDocument = { id: string; label: string; hash: string };
type BankTransaction = {
  id: string;
  label: string;
  date: string;
  amount: string;
  hash: string;
};

type Props = {
  companyId: string;
  incomeYear: number;
  documents: EvidenceDocument[];
  bankTransactions: BankTransaction[];
  existingEvents: RecordedSupportedCorporateEventWire[];
  operationId?: string;
};

const kindLabels: Record<SupportedCorporateEventKind, string> = {
  cash_capital_increase: "Kontant kapitalforhøyelse",
  loss_coverage_capital_reduction: "Kapitalnedsettelse til tapsdekning",
  owner_loan: "Eier låner til selskapet",
  intercompany_loan: "Konserninternt lån",
  bank_loan: "Ordinært banklån",
  group_contribution: "Konsernbidrag",
};

const phases: Record<
  SupportedCorporateEventKind,
  Array<[SupportedCorporateEventPhase, string]>
> = {
  cash_capital_increase: [
    ["binding_subscription", "Bindende tegning"],
    ["restricted_payment", "Innbetaling til sperret konto"],
    ["registered", "Registrert og frigitt"],
  ],
  loss_coverage_capital_reduction: [
    ["decided_not_registered", "Vedtatt, ikke registrert"],
    ["registered", "Registrert etter tidligere vedtak"],
    [
      "first_recognized_after_registration",
      "Først registrert etter gjennomføring",
    ],
  ],
  owner_loan: [["funding", "Utbetaling til selskapet"]],
  intercompany_loan: [["funding", "Utbetaling"]],
  bank_loan: [
    ["disbursement", "Låneutbetaling"],
    ["payment", "Avdrag/renter/gebyr"],
  ],
  group_contribution: [["decision", "Endelig vedtak"]],
};

function Field({
  label,
  name,
  required = true,
  type = "text",
  defaultValue = "",
}: {
  label: string;
  name: string;
  required?: boolean;
  type?: string;
  defaultValue?: string;
}) {
  return (
    <label className="field">
      <span className="fieldLabel">
        {label}
        {required ? <span className="fieldRequired">*</span> : null}
      </span>
      <input
        name={name}
        type={type}
        defaultValue={defaultValue}
        required={required}
      />
    </label>
  );
}

function Confirmations({ items }: { items: Array<[string, string]> }) {
  return (
    <fieldset className="wizardSection">
      <legend>Bekreft avgrensningene</legend>
      {items.map(([name, label]) => (
        <label className="checkboxField" key={name}>
          <input type="checkbox" name={name} required />
          <span>{label}</span>
        </label>
      ))}
    </fieldset>
  );
}

function DocumentSelect({
  documents,
  prefix,
  kind,
  label,
}: {
  documents: EvidenceDocument[];
  prefix: string;
  kind: SupportedCorporateEvidenceKind;
  label: string;
}) {
  const [selected, setSelected] = useState("");
  const document = documents.find((item) => item.id === selected);
  return (
    <>
      <SelectField
        label={label}
        name={`${prefix}Choice`}
        value={selected}
        onChange={setSelected}
        required
      >
        <option value="">Velg dokument</option>
        {documents.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
          </option>
        ))}
      </SelectField>
      <input type="hidden" name={`${prefix}Id`} value={document?.id ?? ""} />
      <input
        type="hidden"
        name={`${prefix}Hash`}
        value={document?.hash ?? ""}
      />
      <input type="hidden" name={`${prefix}Kind`} value={kind} />
    </>
  );
}

function BankSelect({ transactions }: { transactions: BankTransaction[] }) {
  const [selected, setSelected] = useState("");
  const transaction = transactions.find((item) => item.id === selected);
  return (
    <>
      <SelectField
        label="Bankbevegelse"
        name="bankChoice"
        value={selected}
        onChange={setSelected}
        required
      >
        <option value="">Velg bankbevegelse</option>
        {transactions.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
          </option>
        ))}
      </SelectField>
      <input
        type="hidden"
        name="bankTransactionId"
        value={transaction?.id ?? ""}
      />
      <input
        type="hidden"
        name="bankTransactionDate"
        value={transaction?.date ?? ""}
      />
      <input
        type="hidden"
        name="bankSignedAmount"
        value={transaction?.amount ?? ""}
      />
      <input
        type="hidden"
        name="bankSourceHash"
        value={transaction?.hash ?? ""}
      />
    </>
  );
}

function AmountsAndFacts({
  kind,
  phase,
}: {
  kind: SupportedCorporateEventKind;
  phase: SupportedCorporateEventPhase;
}) {
  if (kind === "cash_capital_increase")
    return (
      <>
        <div className="fieldRow">
          <Field label="Pålydende økning (kr)" name="nominalIncrease" />
          <Field label="Overkurs (kr)" name="sharePremium" defaultValue="0" />
        </div>
        <Field
          label="Antall nye aksjer"
          name="issuedShareCount"
          type="number"
        />
        <Confirmations
          items={[
            ["singleOrdinaryClass", "Selskapet har én ordinær aksjeklasse"],
            ["cashOnly", "Innskuddet er bare kontanter"],
            ["bindingSubscription", "Aksjetegningen er bindende"],
            ["fullTimelyPayment", "Hele beløpet er betalt rettidig"],
            [
              "independentConfirmation",
              "Uavhengig innskuddsbekreftelse foreligger",
            ],
            [
              "registerReconciled",
              "Registrert kapital er avstemt mot aksjeeierboken",
            ],
            ["norwegianSubscribersOnly", "Alle tegnere er norske"],
            ["noSpecialTerms", "Ingen særvilkår eller betingelser"],
            [
              "noDirectUseException",
              "Innskuddet er ikke brukt før registrering",
            ],
            ["issueCostsResolved", "Emisjonskostnader og skatt er avklart"],
          ]}
        />
      </>
    );
  if (kind === "loss_coverage_capital_reduction")
    return (
      <>
        <div className="fieldRow">
          <Field label="Nedsettelse (kr)" name="nominalReduction" />
          <Field label="Gammel aksjekapital (kr)" name="oldShareCapital" />
          <Field label="Ny aksjekapital (kr)" name="newShareCapital" />
        </div>
        <Confirmations
          items={[
            ["singleOrdinaryClass", "Én ordinær aksjeklasse"],
            [
              "unchangedOwnersAndShareCount",
              "Eiere og antall aksjer er uendret",
            ],
            ["lossOnly", "Nedsettelsen dekker bare tap"],
            ["lossEvidenced", "Tapet følger av godkjent dokumentasjon"],
            [
              "otherEquityExhausted",
              "Annen tilgjengelig egenkapital er brukt først",
            ],
            ["noValueTransfer", "Ingen verdi overføres til eier"],
            ["noCreditorNotice", "Hendelsen krever ikke kreditorvarsel"],
            ["noSimultaneousCapitalChange", "Ingen samtidig kapitalendring"],
            [
              "registerReconciled",
              "Registreringen er avstemt mot aksjeeierboken",
            ],
          ]}
        />
      </>
    );
  if (kind === "bank_loan")
    return (
      <>
        <Field label="Bank/långiver" name="counterpartyName" />
        <div className="fieldRow">
          <Field
            label="Hovedstol (kr)"
            name="principal"
            defaultValue={phase === "payment" ? "0" : ""}
          />
          <Field label="Renter (kr)" name="interest" defaultValue="0" />
          <Field label="Gebyr (kr)" name="fee" defaultValue="0" />
        </div>
        <Confirmations
          items={[
            ["norwegianCounterparty", "Långiver og valuta er norsk/NOK"],
            ["signedAgreement", "Signert låneavtale foreligger"],
            [
              "lenderAllocationConfirmed",
              "Långiver har spesifisert fordelingen",
            ],
            ["ordinaryTerms", "Lånet har ordinære vilkår"],
            [
              "noComplexTerms",
              "Ingen kassekreditt, refinansiering eller komplekse vilkår",
            ],
          ]}
        />
      </>
    );
  if (kind === "group_contribution")
    return (
      <>
        <Field label="Motpart" name="counterpartyName" />
        <Field
          label="Organisasjonsnummer"
          name="counterpartyOrganizationNumber"
        />
        <div className="fieldRow">
          <Field label="Skattemessig bruttobeløp (kr)" name="grossTaxAmount" />
          <Field label="Tilknyttet skatt (kr)" name="relatedTax" />
          <Field
            label="Regnskapsbeløp etter skatt (kr)"
            name="afterTaxAccountingAmount"
          />
        </div>
        <div className="fieldRow">
          <Field
            label="Eierandel (basispunkter)"
            name="ownershipBasisPoints"
            type="number"
          />
          <Field
            label="Stemmeandel (basispunkter)"
            name="votingBasisPoints"
            type="number"
          />
        </div>
        <label className="field">
          <span className="fieldLabel">Perspektiv</span>
          <select name="perspective">
            <option value="giver">Giver</option>
            <option value="recipient">Mottaker</option>
          </select>
        </label>
        <label className="field">
          <span className="fieldLabel">Relasjon</span>
          <select name="relationship">
            <option value="parent_to_subsidiary">Mor til datter</option>
            <option value="subsidiary_to_parent">Datter til mor</option>
            <option value="sister_to_sister">Søsterselskaper</option>
          </select>
        </label>
        <Confirmations
          items={[
            ["norwegianCounterparty", "Begge selskaper er norske"],
            [
              "yearEndGroupEligibilityProved",
              "Konserntilkårene er dokumentert ved årsslutt",
            ],
            [
              "corporateApprovalEvidenced",
              "Selskapsrettslig vedtak er dokumentert",
            ],
            [
              "distributionCapacityConfirmed",
              "Lovlig utdelingskapasitet er bekreftet",
            ],
            [
              "prudentEquityAndLiquidityConfirmed",
              "Forsvarlig egenkapital og likviditet er bekreftet",
            ],
            [
              "postAcquisitionIncomeProved",
              "Eventuelt inntekt etter oppkjøp er dokumentert",
            ],
            ["impairmentCleared", "Eventuelt nedskrivningsbehov er avklart"],
            ["noEquityMethod", "Egenkapitalmetoden brukes ikke"],
            [
              "noNonCashOrCircularRoute",
              "Ingen tings-, sirkel- eller flerleddet løsning",
            ],
            [
              "consolidationNotRequired",
              "Konsernregnskap er ikke påkrevd eller usikkert",
            ],
          ]}
        />
      </>
    );
  const owner = kind === "owner_loan";
  return (
    <>
      <Field label={owner ? "Eier" : "Motpart"} name="counterpartyName" />
      {!owner ? (
        <Field
          label="Organisasjonsnummer"
          name="counterpartyOrganizationNumber"
        />
      ) : null}
      <Field label="Hovedstol (kr)" name="principal" />
      {!owner ? (
        <>
          <label className="field">
            <span className="fieldLabel">Perspektiv</span>
            <select name="perspective">
              <option value="borrower">Låntaker</option>
              <option value="lender">Långiver</option>
            </select>
          </label>
          <label className="field">
            <span className="fieldLabel">Relasjon</span>
            <select name="relationship">
              <option value="parent_to_subsidiary">Mor til datter</option>
              <option value="other_same_group">Annet i samme konsern</option>
            </select>
          </label>
        </>
      ) : null}
      <Confirmations
        items={
          owner
            ? [
                [
                  "ownerIsRecordedShareholder",
                  "Långiver står i aksjeeierboken",
                ],
                ["norwegianCounterparty", "Långiver er norsk"],
                ["signedAgreement", "Signert avtale foreligger"],
                ["ordinaryTerms", "Vilkårene er ordinære"],
                [
                  "approvalOrExemptionEvidenced",
                  "Godkjenning eller lovlig unntak er dokumentert",
                ],
                [
                  "interestAndTaxTreatmentCleared",
                  "Rente- og skattebehandling er avklart",
                ],
                [
                  "noSecurityOrConversion",
                  "Ingen sikkerhet, garanti eller konvertering",
                ],
                [
                  "noComplexTerms",
                  "Ingen ettergivelse, netting eller andre komplekse vilkår",
                ],
              ]
            : [
                ["norwegianCounterparty", "Motparten er norsk"],
                ["signedAgreement", "Signert avtale foreligger"],
                ["ordinaryTerms", "Vilkårene er ordinære"],
                [
                  "approvalOrExemptionEvidenced",
                  "Godkjenning eller lovlig unntak er dokumentert",
                ],
                ["armLengthConfirmed", "Armlengdes vilkår er bekreftet"],
                ["interestLimitationCleared", "Rentebegrensning er avklart"],
                [
                  "noComplexTerms",
                  "Ingen ettergivelse, konvertering, cash pool eller netting",
                ],
              ]
        }
      />
    </>
  );
}

export function SupportedCorporateEventWizard({
  companyId,
  incomeYear,
  documents,
  bankTransactions,
  existingEvents,
  operationId: initialOperationId,
}: Props) {
  const [kind, setKind] = useState<SupportedCorporateEventKind>("owner_loan");
  const [phase, setPhase] = useState<SupportedCorporateEventPhase>("funding");
  const [reference, setReference] = useState(() => crypto.randomUUID());
  const [operationId] = useState(
    () => initialOperationId ?? crypto.randomUUID(),
  );
  const [reversalOperationId] = useState(() => crypto.randomUUID());
  const existingReferences = useMemo(
    () => existingEvents.filter((event) => event.eventKind === kind),
    [existingEvents, kind],
  );
  const needsBank =
    kind === "owner_loan" ||
    kind === "intercompany_loan" ||
    kind === "bank_loan" ||
    (kind === "cash_capital_increase" && phase !== "binding_subscription");
  const primaryKind: SupportedCorporateEvidenceKind =
    kind === "bank_loan" && phase === "payment"
      ? "lender_statement"
      : kind === "owner_loan" ||
          kind === "intercompany_loan" ||
          kind === "bank_loan"
        ? "signed_agreement"
        : "signed_decision";

  function changeKind(value: string) {
    const next = value as SupportedCorporateEventKind;
    setKind(next);
    setPhase(phases[next][0]![0]);
    setReference(crypto.randomUUID());
  }

  return (
    <div className="wizardForm">
      <Banner variant="info" title="Trygg, smal arbeidsflyt">
        Talli stopper uten å bokføre når avtaler, vedtak, bankbevis, skatt eller
        selskapsrettslige vurderinger ikke er avklart. Produksjonsinnsending
        skjer ikke her.
      </Banner>
      <form action={recordSupportedCorporateEventAction} className="wizardForm">
        <input type="hidden" name="operationId" value={operationId} />
        <input type="hidden" name="returnTo" value="/actions" />
        <input type="hidden" name="companyId" value={companyId} />
        <input type="hidden" name="incomeYear" value={incomeYear} />
        <input type="hidden" name="eventReference" value={reference} />
        <SelectField
          label="Hendelse"
          name="eventKind"
          value={kind}
          onChange={changeKind}
          required
        >
          {Object.entries(kindLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Fase"
          name="phase"
          value={phase}
          onChange={(value) => setPhase(value as SupportedCorporateEventPhase)}
          required
        >
          {phases[kind].map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        {existingReferences.length ? (
          <SelectField
            label="Fortsett tidligere hendelse eller start ny"
            name="eventReferenceChoice"
            value={reference}
            onChange={(value) =>
              setReference(value === "new" ? crypto.randomUUID() : value)
            }
          >
            <option value="new">Start ny hendelse</option>
            {existingReferences.map((event) => (
              <option key={event.eventId} value={event.eventReference}>
                {event.eventDate} · {event.eventReference.slice(0, 8)}
              </option>
            ))}
          </SelectField>
        ) : null}
        <Field label="Hendelsesdato" name="eventDate" type="date" />
        <AmountsAndFacts kind={kind} phase={phase} />
        <DocumentSelect
          documents={documents}
          prefix="primaryDocument"
          kind={primaryKind}
          label={
            primaryKind === "signed_decision"
              ? "Signert vedtak"
              : primaryKind === "lender_statement"
                ? "Långiveroppgave"
                : "Signert avtale"
          }
        />
        {kind === "cash_capital_increase" &&
        phase !== "binding_subscription" ? (
          <DocumentSelect
            documents={documents}
            prefix="supportingDocument1"
            kind="contribution_confirmation"
            label="Innskuddsbekreftelse"
          />
        ) : null}
        {(kind === "cash_capital_increase" && phase === "registered") ||
        kind === "loss_coverage_capital_reduction" ? (
          <DocumentSelect
            documents={documents}
            prefix="supportingDocument2"
            kind="amended_articles"
            label="Oppdaterte vedtekter"
          />
        ) : null}
        {(kind === "cash_capital_increase" ||
          kind === "loss_coverage_capital_reduction") &&
        phase !== "binding_subscription" &&
        phase !== "decided_not_registered" ? (
          <DocumentSelect
            documents={documents}
            prefix="supportingDocument3"
            kind="registration_receipt"
            label="Registreringskvittering"
          />
        ) : null}
        {needsBank ? <BankSelect transactions={bankTransactions} /> : null}
        {(kind === "cash_capital_increase" && phase === "registered") ||
        (kind === "loss_coverage_capital_reduction" &&
          phase !== "decided_not_registered") ? (
          <>
            <DocumentSelect
              documents={documents}
              prefix="sourceDocument"
              kind="shareholder_register"
              label="Aksjeeierbok"
            />
            <input
              type="hidden"
              name="sourceKind"
              value="shareholder_register"
            />
          </>
        ) : null}
        {kind === "group_contribution" ? (
          <>
            <DocumentSelect
              documents={documents}
              prefix="sourceDocument"
              kind="tax_calculation"
              label="Versjonert skatteberegning"
            />
            <input type="hidden" name="sourceKind" value="tax_calculation" />
          </>
        ) : null}
        <SubmitButton pendingLabel="Kontrollerer og bokfører …">
          Kontroller og bokfør
        </SubmitButton>
      </form>

      {existingEvents.length ? (
        <details>
          <summary>Korriger en registrert hendelse</summary>
          <form
            action={reverseSupportedCorporateEventAction}
            className="wizardForm"
          >
            <input
              type="hidden"
              name="operationId"
              value={reversalOperationId}
            />
            <input type="hidden" name="returnTo" value="/actions" />
            <input type="hidden" name="companyId" value={companyId} />
            <input type="hidden" name="incomeYear" value={incomeYear} />
            <label className="field">
              <span className="fieldLabel">Hendelse</span>
              <select name="originalEventId" required>
                {existingEvents.map((event) => (
                  <option key={event.eventId} value={event.eventId}>
                    {event.eventDate} · {kindLabels[event.eventKind]} ·{" "}
                    {event.phase}
                  </option>
                ))}
              </select>
            </label>
            <Field label="Reverseringsdato" name="reversalDate" type="date" />
            <Field label="Begrunnelse" name="reason" />
            <DocumentSelect
              documents={documents}
              prefix="correctionDocument"
              kind="correction_memo"
              label="Signert korrigeringsnotat"
            />
            <SubmitButton pendingLabel="Reverserer …">
              Opprett full reversering
            </SubmitButton>
          </form>
        </details>
      ) : null}
    </div>
  );
}
