import { AlertTriangle, Inbox, Info } from "lucide-react";
import type { ReactNode } from "react";

export function ErrorBanner({
  title,
  message,
  tone = "danger",
}: {
  title: string;
  message?: ReactNode;
  tone?: "danger" | "warning" | "info";
}) {
  const styles = {
    danger: "border-danger-border bg-danger-soft text-danger-text",
    warning: "border-warning-border bg-warning-soft text-warning-text",
    info: "border-primary/30 bg-primary-faint text-primary",
  }[tone];

  const Icon = tone === "info" ? Info : AlertTriangle;

  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-card border px-5 py-4 ${styles}`}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-semibold">{title}</p>
        {message && <p className="mt-0.5 text-[13px] leading-relaxed">{message}</p>}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-chip">
        <Inbox className="h-6 w-6 text-ink-faint" aria-hidden="true" />
      </span>
      <p className="mt-4 text-[15px] font-semibold text-ink">{title}</p>
      {message && (
        <p className="mt-1 max-w-md text-[13px] leading-relaxed text-ink-muted">
          {message}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-16 text-ink-muted">
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-primary"
        aria-hidden="true"
      />
      <span className="text-sm">{label}</span>
    </div>
  );
}
