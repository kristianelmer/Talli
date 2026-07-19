import type { ReactNode } from "react";

import { cx } from "./cx";
import { AlertTriangle, Check } from "./Icons";

export type BadgeVariant = "success" | "warning" | "danger" | "draft" | "info";

/** Canonical filing/task statuses (see docs/design/README.md §3). */
export type DomainStatus =
  | "utkast"
  | "trenger_gjennomgang"
  | "blokkert"
  | "klar"
  | "levert"
  | "til_regnskapsforer";

const DOMAIN: Record<
  DomainStatus,
  { variant: BadgeVariant; label: string; icon?: "check" | "alert" }
> = {
  utkast: { variant: "draft", label: "Utkast" },
  trenger_gjennomgang: {
    variant: "warning",
    label: "Trenger gjennomgang",
    icon: "alert",
  },
  blokkert: { variant: "danger", label: "Blokkert", icon: "alert" },
  klar: { variant: "success", label: "Klar til innsending", icon: "check" },
  levert: { variant: "success", label: "Levert", icon: "check" },
  til_regnskapsforer: { variant: "info", label: "Til regnskapsfører" },
};

type StatusBadgeProps =
  | {
      /** Map a domain status to its variant, label and icon automatically. */
      status: DomainStatus;
      variant?: never;
      label?: never;
      icon?: never;
      className?: string;
    }
  | {
      status?: never;
      variant: BadgeVariant;
      label: ReactNode;
      icon?: "check" | "alert";
      className?: string;
    };

export function StatusBadge(props: StatusBadgeProps) {
  const resolved = props.status
    ? DOMAIN[props.status]
    : { variant: props.variant, label: props.label, icon: props.icon };

  return (
    <span className={cx("badge", `badge--${resolved.variant}`, props.className)}>
      {resolved.icon === "check" ? <Check size={13} aria-hidden="true" /> : null}
      {resolved.icon === "alert" ? (
        <AlertTriangle size={13} aria-hidden="true" />
      ) : null}
      {resolved.label}
    </span>
  );
}
