"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FilePlus2, Layers, ListOrdered, ShieldCheck } from "lucide-react";

const NAV = [
  { href: "/audit", label: "Audit Request", Icon: FilePlus2 },
  { href: "/requests", label: "Requests", Icon: ListOrdered },
  { href: "/use-cases", label: "Use Cases", Icon: Layers },
];

export function Sidebar() {
  const pathname = usePathname() ?? "";

  const isActive = (href: string) => {
    if (href === "/requests") {
      // Request detail, review and package screens all live under /requests.
      return pathname.startsWith("/requests");
    }
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <aside className="flex w-64 shrink-0 flex-col bg-sidebar max-lg:hidden">
      <div className="flex items-center gap-3 border-b border-sidebar-border px-6 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
          <ShieldCheck className="h-5 w-5 text-white" aria-hidden="true" />
        </span>
        <span className="leading-tight">
          <span className="block text-[15px] font-semibold text-white">AuditEV</span>
          <span className="block text-meta text-sidebar-muted">POC v1.0</span>
        </span>
      </div>

      <nav className="flex-1 px-4 py-5" aria-label="Main">
        <ul className="space-y-1">
          {NAV.map(({ href, label, Icon }) => {
            const active = isActive(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-control px-3 py-2.5 text-sm font-medium transition-colors ${
                    active
                      ? "bg-sidebar-active text-white"
                      : "text-sidebar-text hover:bg-sidebar-active/40"
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-sidebar-border px-6 py-5 text-meta leading-relaxed text-sidebar-muted">
        <p>Internal Use Only</p>
        <p>Audit Operations</p>
      </div>
    </aside>
  );
}

/** Compact top bar shown instead of the rail on small screens. */
export function MobileNav() {
  const pathname = usePathname() ?? "";

  return (
    <div className="sticky top-0 z-20 bg-sidebar px-4 py-3 lg:hidden">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <ShieldCheck className="h-4 w-4 text-white" aria-hidden="true" />
        </span>
        <span className="text-sm font-semibold text-white">AuditEV</span>
      </div>
      <nav className="mt-3 flex gap-2 overflow-x-auto" aria-label="Main">
        {NAV.map(({ href, label, Icon }) => {
          const active =
            href === "/requests"
              ? pathname.startsWith("/requests")
              : pathname === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex shrink-0 items-center gap-2 rounded-control px-3 py-2 text-[13px] font-medium ${
                active ? "bg-sidebar-active text-white" : "text-sidebar-text"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
