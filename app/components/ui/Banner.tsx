import type { ReactNode } from "react";

import { cx } from "./cx";
import { AlertTriangle, Check, Info } from "./Icons";

export type BannerVariant = "info" | "success" | "warning" | "danger";

const ICON = {
  info: Info,
  success: Check,
  warning: AlertTriangle,
  danger: AlertTriangle,
} as const;

type BannerProps = {
  variant?: BannerVariant;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
};

/** Static, page-level alert. For transient notifications use the toast system. */
export function Banner({
  variant = "info",
  title,
  children,
  className,
}: BannerProps) {
  const Icon = ICON[variant];
  return (
    <div
      className={cx("banner", `banner--${variant}`, className)}
      role={variant === "danger" ? "alert" : "status"}
    >
      <Icon className="bannerIcon" size={18} aria-hidden="true" />
      <div className="bannerBody">
        {title ? <p className="bannerTitle">{title}</p> : null}
        {children ? <div className="bannerText">{children}</div> : null}
      </div>
    </div>
  );
}
