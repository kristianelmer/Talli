"use client";

import { createBrowserClient } from "@supabase/ssr";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  inspectOwnerMfa,
  ownerMfaEnrollmentControl,
  ownerMfaCopy,
  startOwnerMfaEnrollment,
  verifyOwnerMfa,
  type OwnerMfaErrorKind,
} from "../lib/owner-mfa";

type OwnerMfaProps = {
  returnTo: string;
  requireFreshChallenge?: boolean;
  supabaseUrl: string;
  supabaseAnonKey: string;
};

type OwnerMfaMode =
  | "loading"
  | "enrollment"
  | "enrolling"
  | "challenge"
  | "verified";

export function OwnerMfa({
  returnTo,
  requireFreshChallenge = false,
  supabaseUrl,
  supabaseAnonKey,
}: OwnerMfaProps) {
  const supabase = useMemo(
    () => createBrowserClient(supabaseUrl, supabaseAnonKey),
    [supabaseAnonKey, supabaseUrl],
  );
  const [mode, setMode] = useState<OwnerMfaMode>("loading");
  const [factorId, setFactorId] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [secret, setSecret] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorKind, setErrorKind] = useState<OwnerMfaErrorKind>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    let active = true;
    void inspectOwnerMfa(supabase.auth.mfa, { requireFreshChallenge }).then((inspection) => {
      if (!active) return;
      if (inspection.kind === "error") {
        setError(inspection.message);
        setErrorKind("status");
        setMode("enrollment");
        return;
      }
      if (inspection.kind === "verified") {
        setMode("verified");
        window.location.assign(returnTo);
        return;
      }
      if (inspection.kind === "challenge") {
        setFactorId(inspection.factorId);
        setMode("challenge");
        return;
      }
      setMode("enrollment");
    });
    return () => {
      active = false;
    };
  }, [requireFreshChallenge, returnTo, supabase]);

  useEffect(() => {
    if (error) {
      errorRef.current?.focus();
    }
  }, [error]);

  async function startEnrollment() {
    setBusy(true);
    setError("");
    setErrorKind(null);
    const enrollment = await startOwnerMfaEnrollment(supabase.auth.mfa);
    setBusy(false);
    if (!enrollment.ok) {
      setError(enrollment.message);
      setErrorKind("enrollment");
      return;
    }
    setFactorId(enrollment.factorId);
    setQrCode(enrollment.qrCode);
    setSecret(enrollment.secret);
    setMode("enrolling");
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setErrorKind(null);
    const verification = await verifyOwnerMfa(
      supabase.auth.mfa,
      factorId,
      verificationCode,
    );
    setBusy(false);
    if (!verification.ok) {
      setError(verification.message);
      setErrorKind("verification");
      return;
    }
    setMode("verified");
    window.location.assign(returnTo);
  }

  const showCodeForm = mode === "enrolling" || mode === "challenge";
  const enrollmentControl = ownerMfaEnrollmentControl({ busy, errorKind });

  return (
    <div className="authCard">
      <div className="appBrand">
        <span className="appBrandMark" aria-hidden="true" />
        <span>Talli</span>
      </div>
      <h1 className="authTitle">{ownerMfaCopy.heading}</h1>
      <p className="authIntro">{requireFreshChallenge
        ? "Bekreft innloggingen på nytt med autentiseringsappen før du fortsetter."
        : ownerMfaCopy.intro}</p>

      {error ? (
        <p
          className="errorText"
          id="ownerMfaError"
          ref={errorRef}
          role="alert"
          tabIndex={-1}
        >
          {error}
        </p>
      ) : null}

      {mode === "loading" ? (
        <p aria-live="polite">Kontrollerer sikkerheten …</p>
      ) : null}

      {mode === "enrollment" ? (
        <button
          className="btn btn--primary"
          type="button"
          onClick={startEnrollment}
          disabled={enrollmentControl.disabled}
        >
          {enrollmentControl.label}
        </button>
      ) : null}

      {mode === "enrolling" ? (
        <div aria-labelledby="ownerMfaScanHeading">
          <h2 id="ownerMfaScanHeading">Skann QR-koden</h2>
          <p id="ownerMfaEnrollmentInstructions">
            Skann koden med en autentiseringsapp. Ikke del eller lagre QR-koden
            eller nøkkelen.
          </p>
          {/* Supabase returns an enrollment-only SVG data URL. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={qrCode}
            alt="QR-kode for å sette opp Talli i autentiseringsappen"
            width={220}
            height={220}
          />
          <p>
            Kan du ikke skanne? Skriv inn nøkkelen manuelt: <code>{secret}</code>
          </p>
        </div>
      ) : null}

      {showCodeForm ? (
        <form className="authForm" onSubmit={verify}>
          <p id="ownerMfaCodeInstructions">
            Åpne autentiseringsappen og skriv inn den sekssifrede koden.
          </p>
          <div className="field">
            <label htmlFor="ownerMfaCode">Sekssifret kode</label>
            <input
              id="ownerMfaCode"
              value={verificationCode}
              onChange={(event) =>
                setVerificationCode(
                  event.target.value.replace(/\D/gu, "").slice(0, 6),
                )
              }
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              aria-describedby={[
                "ownerMfaCodeInstructions",
                error ? "ownerMfaError" : "",
              ].filter(Boolean).join(" ")}
              aria-invalid={Boolean(error)}
              required
            />
          </div>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Bekrefter …" : "Bekreft og fortsett"}
          </button>
        </form>
      ) : null}

      {mode === "verified" ? (
        <p aria-live="polite">Bekreftet. Åpner siden …</p>
      ) : null}
    </div>
  );
}
