"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState } from "react";

import type { EligibilityDecisionResponse } from "../../features/company-access";
import { MarketingEvent } from "../../features/public-acquisition/MarketingEvent";
import { queueMarketingMeasurementEvent } from "../../features/public-acquisition/measurement-client";
import { Banner, Button, LinkButton, SubmitButton } from "../components/ui";
import {
  definitiveEligibilityAction,
  precheckEligibilityAction,
  type EligibilityActionState,
} from "./actions";
import styles from "./eligibility.module.css";

const initialState: EligibilityActionState = {};

function PublicFacts({ result }: { result: EligibilityDecisionResponse }) {
  return (
    <dl aria-label="Offentlige selskapsopplysninger">
      <div>
        <dt>Selskap</dt>
        <dd>{result.publicFacts.name} · {result.publicFacts.orgNumber}</dd>
      </div>
      <div>
        <dt>Organisasjonsform og status</dt>
        <dd>{result.publicFacts.entityType} · {result.publicFacts.statusText}</dd>
      </div>
      <div>
        <dt>Kilde</dt>
        <dd>{result.publicFacts.source}</dd>
      </div>
    </dl>
  );
}

function Result({ result }: { result: EligibilityDecisionResponse }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  if (result.decision === "supported" && result.companyYearPromise) {
    return (
      <>
        <MarketingEvent event="definitive_eligible" surface="eligibility" />
        <section className={styles.result} aria-labelledby="eligibility-result-title">
          <p className={styles.eyebrow}>Passer for Talli</p>
          <h2 id="eligibility-result-title" ref={headingRef} tabIndex={-1}>
            {result.publicFacts.name} kan bruke Talli
          </h2>
          <PublicFacts result={result} />
          <p>
            Selskapsåret {result.accountingYear} bygges komplett fra 1. januar. Tidligere år er
            ikke med.
          </p>
          <div className={styles.primaryAction}>
            <LinkButton
              href="/signup?next=%2Fonboarding"
              block
              onClick={() => queueMarketingMeasurementEvent("signup_start", "signup")}
            >
              Opprett konto og godta
            </LinkButton>
          </div>
          <p className={styles.secondaryLink}>
            Har du konto? <Link href="/login?next=%2Fonboarding">Logg inn</Link>
          </p>
        </section>
      </>
    );
  }
  const title = result.decision === "blocked" ? "Talli passer ikke for dette året" : "Dette må avklares først";
  return (
    <>
      <MarketingEvent
        event={result.provisional ? "provisional_blocked" : "definitive_blocked"}
        surface="eligibility"
        reason={result.decision === "clarify" ? "unknown_material_facts" : "unsupported_company"}
      />
      <section className={styles.result} aria-labelledby="eligibility-result-title">
        <p className={styles.eyebrow}>
          {result.provisional
            ? "Foreløpig svar · Utenfor grensen"
            : result.decision === "blocked"
              ? "Utenfor grensen"
              : "Må avklares"}
        </p>
        <h2 id="eligibility-result-title" ref={headingRef} tabIndex={-1}>{title}</h2>
        <PublicFacts result={result} />
        {result.provisional ? (
          <p>Dette er et foreløpig svar basert bare på offentlige opplysninger.</p>
        ) : null}
        {result.reasonExplanations.length > 0 ? (
          <ul aria-label="Hvorfor du ikke kan gå videre">
            {result.reasonExplanations.map((explanation) => (
              <li key={explanation}>{explanation}</li>
            ))}
          </ul>
        ) : null}
        <p>{result.nextStep}</p>
        <a className={styles.restartLink} href="/sjekk-selskapet">Start på nytt</a>
      </section>
    </>
  );
}

export function EligibilityInterview({
  precheck,
  definitiveAction,
  submitLabel = "Se endelig svar",
  companyId,
}: {
  precheck: EligibilityDecisionResponse;
  definitiveAction: (payload: FormData) => void | Promise<void>;
  submitLabel?: string;
  companyId?: string;
}) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const legendRef = useRef<HTMLLegendElement>(null);
  const question = precheck.questions[index];
  const isLast = index === precheck.questions.length - 1;
  const selected = question ? answers[question.code] : undefined;

  useEffect(() => {
    legendRef.current?.focus();
  }, [index]);

  if (!question) return <Banner variant="danger">Spørsmålene mangler. Start sjekken på nytt.</Banner>;

  return (
    <form action={definitiveAction} className={styles.interview}>
      {companyId ? <input type="hidden" name="companyId" value={companyId} /> : null}
      <input type="hidden" name="orgNumber" value={precheck.publicFacts.orgNumber} />
      <input type="hidden" name="publicFactsSha256" value={precheck.publicFactsSha256} />
      <input type="hidden" name="capabilityManifestVersion" value={precheck.capabilityManifestVersion} />
      <input type="hidden" name="capabilityManifestSha256" value={precheck.capabilityManifestSha256} />
      {precheck.questionCodes.map((code) => (
        <span key={code}>
          <input type="hidden" name="questionCode" value={code} />
          <input type="hidden" name={`answer:${code}`} value={answers[code] ?? ""} />
        </span>
      ))}
      <div className={styles.progress}>
        <span id="eligibility-progress-label">Spørsmål {index + 1} av {precheck.questions.length}</span>
        <progress
          value={index + 1}
          max={precheck.questions.length}
          aria-labelledby="eligibility-progress-label"
        />
      </div>
      <fieldset className={styles.question}>
        <legend ref={legendRef} tabIndex={-1}>{question.prompt}</legend>
        <div className={styles.answers}>
          {(["yes", "no", "unknown"] as const).map((answer) => (
            <label key={answer} className={styles.answer}>
              <input
                type="radio"
                name={`visible:${question.code}`}
                value={answer}
                checked={selected === answer}
                onChange={() => setAnswers((current) => ({ ...current, [question.code]: answer }))}
              />
              {answer === "yes" ? "Ja" : answer === "no" ? "Nei" : "Vet ikke"}
            </label>
          ))}
        </div>
      </fieldset>
      <footer className={styles.controls}>
        {index > 0 ? (
          <Button variant="secondary" onClick={() => setIndex((current) => current - 1)}>
            Tilbake
          </Button>
        ) : <span />}
        {isLast ? (
          <SubmitButton disabled={!selected} pendingLabel="Sjekker…">
            {submitLabel}
          </SubmitButton>
        ) : (
          <Button disabled={!selected} onClick={() => setIndex((current) => current + 1)}>
            Neste
          </Button>
        )}
      </footer>
    </form>
  );
}

export function EligibilityChecker() {
  const [precheckState, precheckAction, precheckPending] = useActionState(
    precheckEligibilityAction,
    initialState,
  );
  const [definitiveState, definitiveAction, definitivePending] = useActionState(
    definitiveEligibilityAction,
    initialState,
  );

  if (definitiveState.result) return <Result result={definitiveState.result} />;
  if (precheckState.result?.decision === "blocked") return <Result result={precheckState.result} />;
  if (precheckState.result) {
    return (
      <>
        <MarketingEvent
          event={precheckState.result.decision === "supported"
            ? "provisional_supported"
            : "provisional_clarify"}
          surface="eligibility"
          reason={precheckState.result.decision === "clarify" ? "missing_required_facts" : null}
        />
        <Banner variant="info" title="Foreløpig svar">
          Offentlige opplysninger ser riktige ut. Svaret er ikke endelig før spørsmålene er ferdige.
        </Banner>
        <PublicFacts result={precheckState.result} />
        {definitiveState.error ? <Banner variant="danger">{definitiveState.error}</Banner> : null}
        <EligibilityInterview
          precheck={precheckState.result}
          definitiveAction={definitiveAction}
        />
        {definitivePending ? <p role="status">Sjekker svarene…</p> : null}
      </>
    );
  }

  return (
    <form action={precheckAction} className={styles.lookup}>
      {precheckState.error ? <Banner variant="danger">{precheckState.error}</Banner> : null}
      <label htmlFor="eligibility-org-number">Organisasjonsnummer</label>
      <input
        id="eligibility-org-number"
        name="orgNumber"
        inputMode="numeric"
        autoComplete="off"
        pattern="[0-9]{9}"
        maxLength={9}
        required
        aria-describedby="eligibility-org-help"
      />
      <p id="eligibility-org-help">Vi henter bare offentlige opplysninger først.</p>
      <SubmitButton block pendingLabel="Henter…" disabled={precheckPending}>
        Sjekk selskapet gratis
      </SubmitButton>
    </form>
  );
}
