import { Banner, LinkButton } from "../components/ui";
import { ownerCopy } from "../lib/copy";

export default function EmailConfirmedPage() {
  const c = ownerCopy.emailConfirmed;
  return (
    <div className="authShell">
      <div className="authCard">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <h1 className="authTitle">{c.title}</h1>
        <Banner variant="success">{c.body}</Banner>
        <LinkButton variant="primary" block href="/dashboard">
          {c.cta}
        </LinkButton>
      </div>
    </div>
  );
}
