"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ownerCopy } from "../lib/copy";

type NavItem = { href: string; label: string };

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
    { href: "/documents", label: ownerCopy.nav.documents },
    { href: "/connections", label: ownerCopy.nav.connections },
    { href: "/selskapsgrense", label: ownerCopy.nav.eligibility },
    { href: "/billing", label: ownerCopy.nav.billing },
  ];
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
              aria-current={isActive(item.href) ? "page" : undefined}
              onClick={() => setOpen(false)}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {isOperator || children ? (
          <div className="appNavRight">
            {isOperator ? (
              <Link
                className="appNavLink"
                href="/operator"
                data-active={isActive("/operator") || undefined}
                data-variant="operator"
                aria-current={isActive("/operator") ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                {ownerCopy.nav.operator}
              </Link>
            ) : null}
            {children}
          </div>
        ) : null}
      </div>
    </>
  );
}
