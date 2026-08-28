"use client";

import { useEffect, useState } from "react";

import {
  grantMarketingConsent,
  loadMarketingConsent,
  loadPendingMarketingWithdrawal,
  removeMarketingConsent,
  removePendingMarketingWithdrawal,
  savePendingMarketingWithdrawal,
  saveMarketingConsent,
  type MarketingCampaignSource,
  type MarketingConsentSession,
} from "./measurement.ts";
import { queueMarketingMeasurementEvent } from "./measurement-client.ts";
import styles from "./MarketingConsent.module.css";
import { withdrawMarketingMeasurementAction } from "./withdrawal-action";

type ConsentState = "checking" | "prompt" | "granted" | "declined";

function campaignSource(): MarketingCampaignSource {
  const source = new URLSearchParams(window.location.search).get("source");
  if (source === null) return "direct";
  if (["organic", "community", "partner", "approved_campaign"].includes(source)) {
    return source as MarketingCampaignSource;
  }
  return "unknown";
}

export function MarketingConsent() {
  const [consentState, setConsentState] = useState<ConsentState>("checking");
  const [session, setSession] = useState<MarketingConsentSession | null>(null);
  const [pendingWithdrawal, setPendingWithdrawal] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const pending = loadPendingMarketingWithdrawal(window.sessionStorage);
    if (pending) {
      removeMarketingConsent(window.sessionStorage);
      setPendingWithdrawal(pending);
      setConsentState("declined");
      setNotice("Måling er slått av. Sletting av den anonyme økten prøves på nytt.");
      void submitWithdrawal(pending);
      return;
    }
    const existing = loadMarketingConsent(window.sessionStorage);
    if (!existing) {
      setConsentState("prompt");
      return;
    }
    let active = existing;
    if (!existing.homeViewRecorded && queueMarketingMeasurementEvent("home_view", "homepage")) {
      active = { ...existing, homeViewRecorded: true };
      saveMarketingConsent(window.sessionStorage, active);
    }
    setSession(active);
    setConsentState("granted");
  }, []);

  useEffect(() => {
    if (!session) return;
    const trackBoundedAction = (event: MouseEvent) => {
      const element = event.target instanceof Element
        ? event.target.closest<HTMLElement>("[data-marketing-event]")
        : null;
      if (
        element?.dataset.marketingEvent === "eligibility_start"
        && element.dataset.marketingSurface === "eligibility"
      ) {
        queueMarketingMeasurementEvent("eligibility_start", "eligibility");
      }
    };
    document.addEventListener("click", trackBoundedAction, { capture: true });
    return () => document.removeEventListener("click", trackBoundedAction, { capture: true });
  }, [session]);

  useEffect(() => {
    if (!session) return;
    const remainingMilliseconds = Math.max(0, session.expiresAt - Date.now());
    const expiryTimer = window.setTimeout(() => {
      removeMarketingConsent(window.sessionStorage);
      setSession(null);
      setConsentState("prompt");
      setNotice("Den anonyme måleøkten er utløpt. Ny måling krever nytt samtykke.");
    }, remainingMilliseconds);
    return () => window.clearTimeout(expiryTimer);
  }, [session]);

  function grant() {
    const granted = grantMarketingConsent(
      window.sessionStorage,
      Date.now(),
      crypto.randomUUID(),
      campaignSource(),
    );
    const homeViewRecorded = queueMarketingMeasurementEvent("home_view", "homepage");
    const active = { ...granted, homeViewRecorded };
    saveMarketingConsent(window.sessionStorage, active);
    setSession(active);
    setConsentState("granted");
    setNotice(
      homeViewRecorded
        ? "Anonym bruksmåling er slått på for denne fanen."
        : "Samtykket er lagret, men måleforespørselen kunne ikke sendes.",
    );
  }

  function decline() {
    removeMarketingConsent(window.sessionStorage);
    setSession(null);
    setConsentState("declined");
    setNotice("Anonym bruksmåling er slått av.");
  }

  async function submitWithdrawal(anonymousSessionId: string) {
    try {
      const withdrawn = await withdrawMarketingMeasurementAction(anonymousSessionId);
      if (!withdrawn) throw new Error("marketing_measurement_withdrawal_failed");
      removePendingMarketingWithdrawal(window.sessionStorage);
      setPendingWithdrawal(null);
      setNotice("Samtykket er trukket, og den anonyme økten er slettet.");
    } catch {
      setPendingWithdrawal(anonymousSessionId);
      setNotice("Måling er slått av, men sletting kunne ikke bekreftes. Prøv igjen.");
    }
  }

  function withdraw() {
    if (!session) return;
    savePendingMarketingWithdrawal(window.sessionStorage, session.anonymousSessionId);
    removeMarketingConsent(window.sessionStorage);
    setSession(null);
    setPendingWithdrawal(session.anonymousSessionId);
    setConsentState("declined");
    setNotice("Måling er slått av. Sletter den anonyme økten …");
    void submitWithdrawal(session.anonymousSessionId);
  }

  if (consentState === "checking") return null;

  return (
    <aside className={styles.panel} aria-labelledby="marketing-consent-title">
      <div className={styles.copy}>
        <strong id="marketing-consent-title">Frivillig, anonym bruksmåling</strong>
        {consentState === "prompt" ? (
          <p>
            Talli kan sende faste hendelseskoder uten navn, e-post, organisasjonsnummer,
            fritekst eller sideadresse. En tilfeldig økt kobler hendelser i høyst 30
            minutter. De faste hendelsene slettes senest etter 90 dager, eller når du
            trekker samtykket i denne fanen. Ingenting lagres eller sendes før du velger
            «Tillat».
          </p>
        ) : (
          <p>{notice || (consentState === "granted"
            ? "Anonym bruksmåling er slått på for denne fanen."
            : "Anonym bruksmåling er slått av.")}</p>
        )}
      </div>
      <div className={styles.actions}>
        {consentState === "granted" ? (
          <button className={styles.secondary} type="button" onClick={withdraw}>
            Trekk samtykke og slett økten
          </button>
        ) : pendingWithdrawal ? (
          <button
            className={styles.secondary}
            type="button"
            onClick={() => void submitWithdrawal(pendingWithdrawal)}
          >
            Prøv sletting igjen
          </button>
        ) : (
          <>
            <button className={styles.primary} type="button" onClick={grant}>
              Tillat anonym måling
            </button>
            <button className={styles.secondary} type="button" onClick={decline}>
              Nei takk
            </button>
          </>
        )}
        <a href="/personvern">Les om personvern</a>
      </div>
      <span className={styles.live} aria-live="polite">{notice}</span>
    </aside>
  );
}
