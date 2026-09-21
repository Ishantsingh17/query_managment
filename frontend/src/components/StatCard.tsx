import {
  CircleAlert,
  CircleCheck,
  Database,
  ListChecks,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import type { ComponentType } from "react";

const ICONS: Record<string, ComponentType<{ className?: string }>> = {
  required: ListChecks,
  found: CircleCheck,
  missing: CircleAlert,
  validation: ShieldCheck,
  sources: Database,
  retries: RefreshCw,
};

type Tone = "neutral" | "success" | "warning" | "danger";

const TONE: Record<Tone, { wrapper: string; value: string; icon: string }> = {
  neutral: {
    wrapper: "border-line bg-card",
    value: "text-ink",
    icon: "text-ink-muted",
  },
  success: {
    wrapper: "border-success-border bg-success-soft",
    value: "text-success-text",
    icon: "text-success-text",
  },
  warning: {
    wrapper: "border-warning-border bg-warning-soft",
    value: "text-warning-text",
    icon: "text-warning-text",
  },
  danger: {
    wrapper: "border-danger-border bg-danger-soft",
    value: "text-danger-text",
    icon: "text-danger-text",
  },
};

export function StatCard({
  label,
  value,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  icon: keyof typeof ICONS;
  tone?: Tone;
}) {
  const Icon = ICONS[icon] ?? ListChecks;
  const styles = TONE[tone];

  // Numbers get the large display size. Word values such as "COMPLETE" or
  // "NEEDS REVIEW" are set smaller with no letter-spacing so a single word
  // fits the tile, and `break-normal` keeps them from ever splitting
  // mid-word ("COMPLET / E"). Multi-word values still wrap at the space.
  const text = String(value);
  const isNumeric = /^\d+$/.test(text);

  return (
    <div
      className={`flex items-center gap-3 overflow-hidden rounded-card border px-4 py-4 shadow-card ${styles.wrapper}`}
    >
      <Icon className={`h-5 w-5 shrink-0 ${styles.icon}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-snug text-ink-muted">{label}</p>
        <p
          title={text}
          className={`font-bold leading-tight ${styles.value} ${
            isNumeric
              ? "text-[22px]"
              : "break-normal text-[13px] uppercase tracking-normal"
          }`}
        >
          {text}
        </p>
      </div>
    </div>
  );
}
