import { randomUUID } from "node:crypto";

import type { BankConnectionPresentation } from "../../../features/banking";
import { disconnectBankConnection, syncBankConnectionAccount } from "../../actions";
import { SubmitButton } from "../../components/ui";

type BankConnectionsProps = {
  connections: readonly BankConnectionPresentation[];
  companyId: string;
  incomeYear: number;
  retryOperationId?: string;
  retryTargetId?: string;
};

export function BankConnections({
  connections,
  companyId,
  incomeYear,
  retryOperationId,
  retryTargetId,
}: BankConnectionsProps) {
  const operationId = (targetId: string) => (
    retryTargetId === targetId && retryOperationId ? retryOperationId : randomUUID()
  );
  return (
    <section className="txSection" aria-labelledby="bank-connections-title">
      <div className="txSectionHead">
        <div>
          <h2 className="sectionTitle" id="bank-connections-title">Banktilkobling</h2>
          <p className="fieldHelp">
            Talli viser bare maskert konto, dekning og sist oppdatert. Bankinnlogging skjer hos banken.
          </p>
        </div>
      </div>
      {connections.length === 0 ? (
        <div className="dataPanel">
          <p>Automatisk banktilkobling er ikke aktivert ennå.</p>
          <p className="fieldHelp">Bruk bankfil under. Filen kontrolleres før du bekrefter import.</p>
        </div>
      ) : connections.map((connection) => (
        <article className="dataPanel" key={connection.id}>
          <div className="txSectionHead">
            <strong>{connection.status}</strong>
            <span className="fieldHelp">{connection.connectorId}</span>
          </div>
          {connection.accounts.length === 0 ? (
            <p className="fieldHelp">Ingen kontoer er tilgjengelige. Koble til på nytt eller bruk bankfil.</p>
          ) : connection.accounts.map((account) => (
            <div key={account.id}>
              <p>{account.label}</p>
              <p className="fieldHelp">Dekning: {account.coverage}</p>
              <p className="fieldHelp">{account.freshness}</p>
              {account.hasGap ? (
                <p className="txPreviewWarn">Perioden er ikke komplett. Synkroniser på nytt eller importer manglende bankfil.</p>
              ) : null}
              {connection.action === "sync" ? (
                <form action={syncBankConnectionAccount}>
                  <input type="hidden" name="operationId" value={operationId(account.id)} />
                  <input type="hidden" name="connectionId" value={connection.id} />
                  <input type="hidden" name="accountId" value={account.id} />
                  <input type="hidden" name="companyId" value={companyId} />
                  <input type="hidden" name="connectorId" value={connection.connectorId} />
                  <input type="hidden" name="incomeYear" value={incomeYear} />
                  <input type="hidden" name="returnTo" value="/transactions" />
                  <SubmitButton variant="secondary" pendingLabel="Synkroniserer …">
                    Synkroniser nå
                  </SubmitButton>
                </form>
              ) : null}
            </div>
          ))}
          {connection.action === "reconnect" || connection.action === "continue" ? (
            <p className="fieldHelp">
              Automatisk fornyelse er stengt til bankleverandøren er aktivert. Importer den manglende perioden under.
            </p>
          ) : null}
          {connection.action !== "connect" ? (
            <form action={disconnectBankConnection}>
              <input type="hidden" name="operationId" value={operationId(connection.id)} />
              <input type="hidden" name="connectionId" value={connection.id} />
              <input type="hidden" name="companyId" value={companyId} />
              <input type="hidden" name="connectorId" value={connection.connectorId} />
              <input type="hidden" name="incomeYear" value={incomeYear} />
              <input type="hidden" name="returnTo" value="/transactions" />
              <SubmitButton variant="ghost" pendingLabel="Kobler fra …">
                Koble fra
              </SubmitButton>
            </form>
          ) : null}
        </article>
      ))}
    </section>
  );
}
