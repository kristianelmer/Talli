import { createCompanyWorkspace, demoWorkspace, readinessSummary, statusLabel } from "./lib/workspace.mjs";

type Filing = {
  name: string;
  status: string;
  issues: string[];
};

type DocumentRow = {
  id: string;
  name: string;
  linkedTo: string;
  status: string;
};

type ReviewComment = {
  id: string;
  target: string;
  body: string;
  severity: string;
};

type WorkspaceView = {
  company: {
    orgNumber: string;
    companyName: string;
    incomeYear: number;
  };
  supportBoundary: {
    message: string;
  };
  filings: Filing[];
  workflowSteps: string[];
  documents: DocumentRow[];
  reviewComments: ReviewComment[];
};

const unsupportedCompany = createCompanyWorkspace({
  orgNumber: "123456789",
  companyName: "Demo ENK",
  entityType: "ENK",
});

export default function Home() {
  const workspace = demoWorkspace as WorkspaceView;
  const summary = readinessSummary(demoWorkspace);

  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primær">
        <div className="brand">
          <span className="brandMark" aria-hidden="true" />
          <span>Talli</span>
        </div>
        <div className="navLinks">
          <a href="#oppsett">Oppsett</a>
          <a href="#filingstatus">Filingstatus</a>
          <a href="#dokumenter">Dokumenter</a>
          <a href="#gjennomgang">Gjennomgang</a>
        </div>
      </nav>

      <section className="workspace">
        <div className="intro">
          <p className="eyebrow">Eierstyrt filing</p>
          <h1>{workspace.company.companyName}</h1>
          <p className="lede">
            Årsloop for enkel holding AS: selskapsoppsett, holdinghandlinger, dokumenter,
            filingstatus og filingforhåndsvisning.
          </p>
          <div className="actions">
            <a className="primaryButton" href="#filingstatus">
              Se filing-status
            </a>
            <a className="secondaryButton" href="#oppsett">
              Sjekk supportgrense
            </a>
          </div>
        </div>

        <aside className="statusPanel" aria-label="Filing-status">
          <div className="panelHeader">
            <span>{workspace.company.orgNumber}</span>
            <strong>{workspace.company.incomeYear}</strong>
          </div>
          <div className="metricGrid">
            <div>
              <span>Klar</span>
              <strong>{summary.ready}</strong>
            </div>
            <div>
              <span>Advarsler</span>
              <strong>{summary.warnings}</strong>
            </div>
            <div>
              <span>Blokkert</span>
              <strong>{summary.blocked}</strong>
            </div>
          </div>
        </aside>
      </section>

      <section id="oppsett" className="band">
        <div className="sectionHeader">
          <p className="eyebrow">Selskapsoppsett</p>
          <h2>AS går videre. Andre selskapsformer stoppes.</h2>
        </div>
        <div className="setupGrid">
          <div className="dataPanel">
            <span className="panelLabel">Støttet selskap</span>
            <strong>{workspace.company.companyName}</strong>
            <p>{workspace.supportBoundary.message}</p>
          </div>
          <div className="dataPanel blocked">
            <span className="panelLabel">Blokkert eksempel</span>
            <strong>{unsupportedCompany.company.companyName}</strong>
            <p>{unsupportedCompany.supportBoundary.message}</p>
          </div>
        </div>
      </section>

      <section id="filingstatus" className="band mutedBand">
        <div className="sectionHeader">
          <p className="eyebrow">Filingstatus</p>
          <h2>Separate gates, delt årsdata.</h2>
        </div>
        <div className="readinessGrid">
          {workspace.filings.map((filing) => (
            <div className="readinessItem" key={filing.name}>
              <span>{filing.name}</span>
              <strong data-status={filing.status}>{statusLabel(filing.status)}</strong>
              {filing.issues.map((issue) => (
                <p key={issue}>{issue}</p>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="split">
        <div>
          <p className="eyebrow">Eierløype</p>
          <h2>Ingen VAT, payroll eller faktura i første flate.</h2>
          <p>
            Webskallet holder seg til domenemotoren: enkel holding AS, strukturert årsdata,
            dokumentstatus og gjennomgang før eier sender inn.
          </p>
        </div>
        <ol className="actionList">
          {workspace.workflowSteps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section id="dokumenter" className="band">
        <div className="sectionHeader">
          <p className="eyebrow">Dokumenter</p>
          <h2>Dokumentstatus følger filing readiness og arkiv.</h2>
        </div>
        <div className="table">
          {workspace.documents.map((document) => (
            <div className="tableRow" key={document.id}>
              <span>{document.name}</span>
              <span>{document.linkedTo}</span>
              <strong data-status="warning">{statusLabel(document.status)}</strong>
            </div>
          ))}
        </div>
      </section>

      <section id="gjennomgang" className="archive">
        <p className="eyebrow">Regnskapsførergjennomgang</p>
        <h2>Kommentarer er rådgivende. Hard systemblokk stopper fortsatt filing.</h2>
        <div className="reviewList">
          {workspace.reviewComments.map((comment) => (
            <div className="reviewItem" key={comment.id}>
              <span>{comment.target}</span>
              <p>{comment.body}</p>
              <strong>{statusLabel(comment.severity)}</strong>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
