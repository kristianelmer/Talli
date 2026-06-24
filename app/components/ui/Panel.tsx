import type { ReactNode } from "react";

import { cx } from "./cx";

type PanelProps = {
  title?: ReactNode;
  /** Rendered on the right of the header (e.g. an action button or badge). */
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
};

/** Titled container with an optional header actions slot and footer. */
export function Panel({
  title,
  actions,
  footer,
  children,
  className,
}: PanelProps) {
  return (
    <section className={cx("panel", className)}>
      {title || actions ? (
        <header className="panelHead">
          {title ? <h2 className="panelTitle">{title}</h2> : <span />}
          {actions}
        </header>
      ) : null}
      <div className="panelBody">{children}</div>
      {footer ? <footer className="panelFooter">{footer}</footer> : null}
    </section>
  );
}
