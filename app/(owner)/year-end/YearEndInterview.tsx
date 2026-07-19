"use client";

import { useMemo, useState } from "react";

import { saveYearEndInterview } from "../../actions";
import { Banner, Stepper, SubmitButton } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import {
  buildYearEndInterviewInitialAnswers,
  noActivityConfirmed,
  type RegisteredYearEndActivity,
  type YearEndInterviewAnswers,
} from "../../lib/annual-data";

type AnswerKey = keyof YearEndInterviewAnswers;
type RegisteredKey = keyof RegisteredYearEndActivity;

type Props = {
  companyId: string;
  incomeYear: number;
  initialAnswers: Partial<YearEndInterviewAnswers> | null;
  initialFte: number | null;
  registered: RegisteredYearEndActivity;
};

const ACTIVITY_KEYS: AnswerKey[] = [
  "shares_owned_at_year_end",
  "bought_or_sold_shares",
  "received_dividends",
  "declared_owner_dividends",
  "shareholder_loans",
  "paid_costs",
];
const CONTROL_KEYS: AnswerKey[] = ["bank_balance_confirmed", "has_unpaid_items"];
const APPROVAL_KEYS: AnswerKey[] = [
  "general_meeting_approved",
  "authority_to_submit_confirmed",
];
const ALL_KEYS: AnswerKey[] = [
  ...ACTIVITY_KEYS,
  ...CONTROL_KEYS,
  ...APPROVAL_KEYS,
];

export function YearEndInterview({
  companyId,
  incomeYear,
  initialAnswers,
  initialFte,
  registered,
}: Props) {
  const c = ownerCopy.yearEnd;

  const [answers, setAnswers] = useState<Record<AnswerKey, boolean>>(() =>
    buildYearEndInterviewInitialAnswers(initialAnswers, registered),
  );
  const [fte, setFte] = useState(initialFte != null ? String(initialFte) : "0");
  const [step, setStep] = useState(0);

  const set = (key: AnswerKey, value: boolean) =>
    setAnswers((prev) => ({ ...prev, [key]: value }));

  const fullAnswers = useMemo(
    () => buildYearEndInterviewInitialAnswers(answers, registered),
    [answers, registered],
  );
  const noActivity = noActivityConfirmed(fullAnswers);

  const reminders = useMemo(
    () =>
      (Object.keys(c.consistency) as RegisteredKey[]).filter(
        (key) => answers[key] && !registered[key],
      ),
    [answers, registered, c.consistency],
  );
  const blocks = useMemo(() => {
    const list: string[] = [];
    if (answers.has_unpaid_items) list.push(c.blocks.unpaidItems);
    if (!answers.general_meeting_approved) list.push(c.blocks.generalMeeting);
    if (!answers.authority_to_submit_confirmed) list.push(c.blocks.authority);
    return list;
  }, [answers, c.blocks]);

  const steps = [
    c.steps.activity,
    c.steps.control,
    c.steps.approval,
    c.steps.summary,
  ];
  const heads = [
    c.stepHeads.activity,
    c.stepHeads.control,
    c.stepHeads.approval,
    c.stepHeads.summary,
  ];
  const head = heads[step];
  const isLast = step === steps.length - 1;

  return (
    <form action={saveYearEndInterview} className="interview wizardForm">
      <input type="hidden" name="companyId" value={companyId} />
      <input type="hidden" name="incomeYear" value={incomeYear} />
      <input type="hidden" name="returnTo" value="/dashboard" />
      <input
        type="hidden"
        name="annualFullTimeEquivalents"
        value={fte.trim() === "" ? "0" : fte}
      />
      {ALL_KEYS.map((key) =>
        fullAnswers[key] ? (
          <input key={key} type="hidden" name={key} value="on" />
        ) : null,
      )}

      <Stepper steps={steps} current={step} />
      <header className="wizardHead">
        <h1 className="wizardTitle">{head.title}</h1>
        <p className="wizardIntro">{head.intro}</p>
      </header>

      {step === 0 ? (
        <div className="qList">
          {ACTIVITY_KEYS.map((key) => (
            <Question
              key={key}
              answerKey={key}
              value={fullAnswers[key]}
              onChange={(value) => set(key, value)}
              hint={
                fullAnswers[key] &&
                key in c.consistency &&
                !registered[key as RegisteredKey]
                  ? c.consistency[key]
                  : null
              }
            />
          ))}
        </div>
      ) : null}

      {step === 1 ? (
        <div className="qList">
          <Question
            answerKey="bank_balance_confirmed"
            value={answers.bank_balance_confirmed}
            onChange={(value) => set("bank_balance_confirmed", value)}
            hint={
              !answers.bank_balance_confirmed
                ? c.warnings.bankNotConfirmed
                : null
            }
            hintVariant="warning"
          />
          <Question
            answerKey="has_unpaid_items"
            value={answers.has_unpaid_items}
            onChange={(value) => set("has_unpaid_items", value)}
            hint={answers.has_unpaid_items ? c.blocks.unpaidItems : null}
            hintVariant="danger"
          />
        </div>
      ) : null}

      {step === 2 ? (
        <div className="qList">
          <Question
            answerKey="general_meeting_approved"
            value={answers.general_meeting_approved}
            onChange={(value) => set("general_meeting_approved", value)}
            hint={
              !answers.general_meeting_approved ? c.blocks.generalMeeting : null
            }
            hintVariant="danger"
          />
          <Question
            answerKey="authority_to_submit_confirmed"
            value={answers.authority_to_submit_confirmed}
            onChange={(value) => set("authority_to_submit_confirmed", value)}
            hint={
              !answers.authority_to_submit_confirmed ? c.blocks.authority : null
            }
            hintVariant="danger"
          />
          <label className="field">
            <span className="fieldLabel">{c.fteLabel}</span>
            <input
              inputMode="decimal"
              value={fte}
              onChange={(event) => setFte(event.target.value)}
            />
            <span className="fieldHelp">{c.fteHelp}</span>
          </label>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="summaryBlock">
          <h2 className="summaryHeading">{c.summary.activityTitle}</h2>
          {noActivity ? (
            <Banner variant="info">{c.summary.noActivity}</Banner>
          ) : ACTIVITY_KEYS.some((key) => fullAnswers[key]) ? (
            <ul className="summaryList">
              {ACTIVITY_KEYS.filter((key) => fullAnswers[key]).map((key) => (
                <li key={key}>{c.activityLabels[key]}</li>
              ))}
            </ul>
          ) : (
            <p className="cardNote">{c.summary.noneActive}</p>
          )}

          {blocks.length > 0 ? (
            <div className="summarySection">
              <h2 className="summaryHeading">{c.summary.blocksTitle}</h2>
              {blocks.map((message) => (
                <Banner key={message} variant="danger">
                  {message}
                </Banner>
              ))}
            </div>
          ) : null}

          {reminders.length > 0 ? (
            <div className="summarySection">
              <h2 className="summaryHeading">{c.summary.remindersTitle}</h2>
              {reminders.map((key) => (
                <Banner key={key} variant="warning">
                  {c.consistency[key]}
                </Banner>
              ))}
            </div>
          ) : null}

          {blocks.length === 0 && reminders.length === 0 ? (
            <Banner variant="success">{c.summary.allClear}</Banner>
          ) : null}

          <p className="cardNote">{c.resumeNote}</p>
        </div>
      ) : null}

      <footer className="interviewFooter">
        {step > 0 ? (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setStep((value) => value - 1)}
          >
            {c.back}
          </button>
        ) : (
          <span />
        )}
        {isLast ? (
          <SubmitButton pendingLabel={c.pending}>{c.submit}</SubmitButton>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setStep((value) => value + 1)}
          >
            {c.next}
          </button>
        )}
      </footer>
    </form>
  );
}

function Question({
  answerKey,
  value,
  onChange,
  hint,
  hintVariant = "info",
}: {
  answerKey: AnswerKey;
  value: boolean;
  onChange: (value: boolean) => void;
  hint?: string | null;
  hintVariant?: "info" | "warning" | "danger";
}) {
  const c = ownerCopy.yearEnd;
  const question = c.questions[answerKey];
  return (
    <div className="qItem">
      <p className="qPrompt">{question.q}</p>
      {question.help ? <p className="qHelp">{question.help}</p> : null}
      <div className="segmented" role="group" aria-label={question.q}>
        <button
          type="button"
          className="segmentedBtn"
          aria-pressed={value}
          data-active={value ? "true" : undefined}
          onClick={() => onChange(true)}
        >
          {c.yes}
        </button>
        <button
          type="button"
          className="segmentedBtn"
          aria-pressed={!value}
          data-active={!value ? "true" : undefined}
          onClick={() => onChange(false)}
        >
          {c.no}
        </button>
      </div>
      {hint ? (
        <Banner variant={hintVariant} className="qHint">
          {hint}
        </Banner>
      ) : null}
    </div>
  );
}
