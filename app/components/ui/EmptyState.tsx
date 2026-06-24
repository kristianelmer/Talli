import type { ReactNode } from "react";

import { cx } from "./cx";

type EmptyStateProps = {
  /** A small mark/illustration (e.g. an icon). Rendered in a soft brand circle. */
  icon?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  /** A single primary action (e.g. a Button or LinkButton). */
  action?: ReactNode;
  className?: string;
};

/** Calm, non-alarming empty state: mark + one line + a single action. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div className={cx("emptyState", className)}>
      {icon ? <span className="emptyStateMark">{icon}</span> : null}
      <p className="emptyStateTitle">{title}</p>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}
