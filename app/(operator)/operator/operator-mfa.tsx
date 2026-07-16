"use client";

import { createBrowserClient } from "@supabase/ssr";
import { useEffect, useMemo, useState, type FormEvent } from "react";

type OperatorMfaProps = {
  supabaseUrl: string;
  supabaseAnonKey: string;
};

type MfaMode = "loading" | "idle" | "enrolling" | "challenge" | "verified";

export function OperatorMfa({ supabaseUrl, supabaseAnonKey }: OperatorMfaProps) {
  const supabase = useMemo(
    () => createBrowserClient(supabaseUrl, supabaseAnonKey),
    [supabaseAnonKey, supabaseUrl],
  );
  const [mode, setMode] = useState<MfaMode>("loading");
  const [factorId, setFactorId] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void (async () => {
      const assurance = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
      if (!active) return;
      if (assurance.error) {
        setError("MFA-status kunne ikke leses.");
        setMode("idle");
        return;
      }
      const factors = await supabase.auth.mfa.listFactors();
      if (!active) return;
      if (factors.error) {
        setError("MFA-faktorer kunne ikke leses.");
        setMode("idle");
        return;
      }
      const totpFactor = factors.data.totp[0];
      if (totpFactor) {
        setFactorId(totpFactor.id);
      }
      if (assurance.data.currentLevel === "aal2") {
        setMode("verified");
        return;
      }
      if (totpFactor) {
        setMode("challenge");
        return;
      }
      setMode("idle");
    })();
    return () => {
      active = false;
    };
  }, [supabase]);

  async function startEnrollment() {
    setBusy(true);
    setError("");
    const enrollment = await supabase.auth.mfa.enroll({
      factorType: "totp",
      friendlyName: "Talli produksjonsoperatør",
    });
    setBusy(false);
    if (enrollment.error) {
      setError("MFA-registreringen kunne ikke startes.");
      return;
    }
    setFactorId(enrollment.data.id);
    setQrCode(enrollment.data.totp.qr_code);
    setMode("enrolling");
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!factorId || !/^\d{6}$/u.test(verificationCode)) {
      setError("Skriv den sekssifrede koden fra autentiseringsappen.");
      return;
    }
    setBusy(true);
    setError("");
    const verification = await supabase.auth.mfa.challengeAndVerify({
      factorId,
      code: verificationCode,
    });
    setBusy(false);
    if (verification.error) {
      setError("Koden ble ikke godkjent. Vent på en ny kode og prøv igjen.");
      return;
    }
    window.location.assign("/operator?authority=authority_mfa_ready");
  }

  return (
    <div className="dataPanel formPanel widePanel">
      <h3>Operatør · AAL2/MFA</h3>
      <p>Produksjonsoperasjoner krever en fersk kode fra en autentiseringsapp.</p>
      {error ? <p className="errorText">{error}</p> : null}
      {mode === "loading" ? <p>Kontrollerer MFA-status …</p> : null}
      {mode === "verified" ? (
        <>
          <p className="successText">Denne økten er bekreftet med AAL2.</p>
          {factorId ? (
            <button
              className="secondaryButton"
              type="button"
              onClick={() => {
                setError("");
                setVerificationCode("");
                setMode("challenge");
              }}
            >
              Bekreft AAL2 på nytt
            </button>
          ) : null}
        </>
      ) : null}
      {mode === "idle" ? (
        <button className="secondaryButton" type="button" onClick={startEnrollment} disabled={busy}>
          {busy ? "Starter …" : "Sett opp autentiseringsapp"}
        </button>
      ) : null}
      {mode === "enrolling" && qrCode ? (
        <>
          <p>Skann QR-koden med en autentiseringsapp. QR-koden skal ikke deles eller lagres.</p>
          {/* Supabase returns a data-URL containing the enrollment-only SVG. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={qrCode} alt="QR-kode for Talli operatør-MFA" width={220} height={220} />
        </>
      ) : null}
      {mode === "enrolling" || mode === "challenge" ? (
        <form className="formPanel" onSubmit={verify}>
          <label>
            Sekssifret kode
            <input
              value={verificationCode}
              onChange={(event) => setVerificationCode(event.target.value.replace(/\D/gu, "").slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              required
            />
          </label>
          <button className="secondaryButton" type="submit" disabled={busy}>
            {busy ? "Bekrefter …" : "Bekreft AAL2"}
          </button>
        </form>
      ) : null}
    </div>
  );
}
