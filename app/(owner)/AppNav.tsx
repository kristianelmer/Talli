"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ownerCopy } from "../lib/copy";

type NavItem = { href: string; label: string; variant?: "operator" };

type AppNavProps = {
  isOperator: boolean;
  children?: ReactNode;
};

export function AppNav({ isOperator, children }: AppNavProps) {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);

  const items: NavItem[] = [
    { href: "/dashboard", label: ownerCopy.nav.overview },
    { href: "/actions", label: ownerCopy.nav.actions },
    { href: "/transactions", label: ownerCopy.nav.transactions },
    { href: "/year-end", label: ownerCopy.nav.yearEnd },
    { href: "/filing", label: ownerCopy.nav.filing },
    { href: "/connections", label: ownerCopy.nav.connections },
    { href: "/documents", label: ownerCopy.nav.documents },
    { href: "/billing", label: ownerCopy.nav.billing },
    { href: "/workspace", label: ownerCopy.nav.workspace },
  ];
  if (isOperator) {
    items.push({ href: "/operator", label: ownerCopy.nav.operator, variant: "operator" });
  }

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      <button
        type="button"
        className="appMenuToggle"
        aria-expanded={open}
        aria-controls="appPrimaryMenu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="appMenuToggleBars" aria-hidden="true" />
        <span>{ownerCopy.nav.menu}</span>
      </button>
      <div id="appPrimaryMenu" className="appMenu" data-open={open || undefined}>
        <nav className="appNav" aria-label="Hovedmeny">
          {items.map((item) => (
            <Link
              key={item.href}
              className="appNavLink"
              href={item.href}
              data-active={isActive(item.href) || undefined}
              data-variant={item.variant}
              aria-current={isActive(item.href) ? "page" : undefined}
              onClick={() => setOpen(false)}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {children ? <div className="appNavRight">{children}</div> : null}
      </div>
    </>
  );
}
