"use client";

import { useActionState } from "react";
import { initialMfaActionState } from "../../lib/mfa";
import { beginTotpEnrollment, verifyTotpStepUp } from "./actions";

type VerifiedFactor = {
  id: string;
  label: string;
};

export function MfaPanel({ verifiedFactors, currentLevel }: { verifiedFactors: VerifiedFactor[]; currentLevel: string }) {
  const [enrollment, enrollAction, enrollPending] = useActionState(beginTotpEnrollment, initialMfaActionState);
  const [verification, verifyAction, verifyPending] = useActionState(verifyTotpStepUp, initialMfaActionState);

  return (
    <div className="setupGrid">
      <section className="dataPanel formPanel">
        <span className="panelLabel">Status</span>
        <strong>{currentLevel === "aal2" ? "AAL2" : "AAL1"}</strong>
        <p>Verifiserte TOTP-faktorer: {verifiedFactors.length}</p>
        <p>En sensitiv handling krever en TOTP-verifisering som er høyst 15 minutter gammel.</p>
        <a className="secondaryButton" href="/">Tilbake til arbeidsflaten</a>
      </section>

      {verifiedFactors.length === 0 ? (
        <section className="dataPanel formPanel">
          <span className="panelLabel">Registrer TOTP</span>
          {enrollment.status !== "enrollment_started" ? (
            <form action={enrollAction}>
              <p>Koble Talli til en autentiseringsapp. Hemmeligheten vises bare i dette registreringssteget.</p>
              <button className="primaryButton" type="submit" disabled={enrollPending}>
                {enrollPending ? "Starter …" : "Start registrering"}
              </button>
            </form>
          ) : null}
          {enrollment.message ? (
            <p className={enrollment.status === "error" ? "errorText" : undefined}>{enrollment.message}</p>
          ) : null}
          {enrollment.enrollment ? (
            <>
              {/* Supabase returns an SVG enrollment secret. Never log or persist it. */}
              <img src={enrollment.enrollment.qrCodeDataUrl} alt="QR-kode for Talli TOTP" width="220" height="220" />
              <label>
                Manuell hemmelighet
                <input type="password" readOnly value={enrollment.enrollment.secret} autoComplete="off" />
              </label>
              <form className="formPanel" action={verifyAction}>
                <input type="hidden" name="factorId" value={enrollment.enrollment.factorId} />
                <label>
                  Sekssifret kode
                  <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required />
                </label>
                <button className="primaryButton" type="submit" disabled={verifyPending}>
                  {verifyPending ? "Verifiserer …" : "Bekreft TOTP"}
                </button>
              </form>
            </>
          ) : null}
        </section>
      ) : (
        <form className="dataPanel formPanel" action={verifyAction}>
          <span className="panelLabel">Ny step-up</span>
          <label>
            TOTP-faktor
            <select name="factorId" required defaultValue={verifiedFactors[0]?.id}>
              {verifiedFactors.map((factor) => <option key={factor.id} value={factor.id}>{factor.label}</option>)}
            </select>
          </label>
          <label>
            Sekssifret kode
            <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required />
          </label>
          <button className="primaryButton" type="submit" disabled={verifyPending}>
            {verifyPending ? "Verifiserer …" : "Bekreft step-up"}
          </button>
          {verification.message ? (
            <p className={verification.status === "error" ? "errorText" : undefined}>{verification.message}</p>
          ) : null}
        </form>
      )}
    </div>
  );
}
