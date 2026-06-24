import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "./cx";

type CardProps = HTMLAttributes<HTMLDivElement>;

/** Plain surface card. Compose freely; use StatCard for the label/value tile. */
export function Card({ className, ...rest }: CardProps) {
  return <div className={cx("card", className)} {...rest} />;
}

type StatCardProps = {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  className?: string;
};

export function StatCard({ label, value, note, className }: StatCardProps) {
  return (
    <div className={cx("card", className)}>
      <span className="cardLabel">{label}</span>
      <span className="cardValue">{value}</span>
      {note ? <p className="cardNote">{note}</p> : null}
    </div>
  );
}
