import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  Loader2,
  MessageCircleQuestion,
  Search,
  ShieldCheck,
  UserRound,
  XCircle,
} from "lucide-react";
import type { ComponentType } from "react";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-chip text-ink-soft",
  info: "bg-primary-soft text-primary",
  success: "bg-success-soft text-success-text",
  warning: "bg-warning-soft text-warning-text",
  danger: "bg-danger-soft text-danger-text",
};

interface BadgeSpec {
  label: string;
  tone: Tone;
  Icon: ComponentType<{ className?: string }>;
}

/**
 * Every badge pairs an icon with text, so status never relies on colour
 * alone (accessibility requirement in the UI brief).
 */
const REQUEST_BADGES: Record<string, BadgeSpec> = {
  RECEIVED: { label: "RECEIVED", tone: "neutral", Icon: Clock },
  UNDERSTANDING: { label: "UNDERSTANDING", tone: "info", Icon: Loader2 },
  PLANNING: { label: "PLANNING", tone: "info", Icon: Loader2 },
  RETRIEVING: { label: "RETRIEVING", tone: "info", Icon: Search },
  VALIDATING: { label: "VALIDATING", tone: "info", Icon: Loader2 },
  INCOMPLETE: { label: "INCOMPLETE", tone: "warning", Icon: AlertTriangle },
  NEEDS_INPUT: { label: "INPUT REQUIRED", tone: "warning", Icon: MessageCircleQuestion },
  READY_FOR_REVIEW: { label: "READY FOR REVIEW", tone: "info", Icon: Eye },
  APPROVED: { label: "APPROVED", tone: "success", Icon: CheckCircle2 },
  REJECTED: { label: "REJECTED", tone: "danger", Icon: XCircle },
  ERROR: { label: "ERROR", tone: "danger", Icon: XCircle },
  UNSUPPORTED: { label: "UNSUPPORTED", tone: "warning", Icon: AlertTriangle },
};

const EVIDENCE_BADGES: Record<string, BadgeSpec> = {
  PENDING: { label: "PENDING", tone: "neutral", Icon: Clock },
  SEARCHING: { label: "SEARCHING", tone: "info", Icon: Loader2 },
  FOUND: { label: "FOUND", tone: "info", Icon: CheckCircle2 },
  MISSING: { label: "MISSING", tone: "warning", Icon: AlertTriangle },
  VALIDATED: { label: "VALIDATED", tone: "success", Icon: ShieldCheck },
};

const VALIDATION_BADGES: Record<string, BadgeSpec> = {
  COMPLETE: { label: "COMPLETE", tone: "success", Icon: ShieldCheck },
  INCOMPLETE: { label: "INCOMPLETE", tone: "warning", Icon: AlertTriangle },
  NEEDS_REVIEW: { label: "NEEDS REVIEW", tone: "warning", Icon: UserRound },
  ERROR: { label: "ERROR", tone: "danger", Icon: XCircle },
};

const SIZE_CLASS = {
  sm: "px-2 py-0.5 text-[11px] gap-1",
  md: "px-2.5 py-1 text-meta gap-1.5",
  lg: "px-3 py-1.5 text-[13px] gap-1.5",
} as const;

const ICON_SIZE = { sm: "h-3 w-3", md: "h-3.5 w-3.5", lg: "h-4 w-4" } as const;

interface Props {
  status: string;
  kind?: "request" | "evidence" | "validation";
  size?: keyof typeof SIZE_CLASS;
  className?: string;
}

export function StatusBadge({
  status,
  kind = "request",
  size = "md",
  className = "",
}: Props) {
  const table =
    kind === "evidence"
      ? EVIDENCE_BADGES
      : kind === "validation"
        ? VALIDATION_BADGES
        : REQUEST_BADGES;

  const spec: BadgeSpec =
    table[status] ?? {
      label: status.replace(/_/g, " "),
      tone: "neutral",
      Icon: Clock,
    };

  const spin =
    spec.Icon === Loader2 ? "animate-spin" : "";

  return (
    <span
      className={`inline-flex items-center rounded-md font-semibold uppercase tracking-[0.04em] ${TONE_CLASS[spec.tone]} ${SIZE_CLASS[size]} ${className}`}
    >
      <spec.Icon className={`${ICON_SIZE[size]} ${spin}`} aria-hidden="true" />
      {spec.label}
    </span>
  );
}

/** Small inline PASS / FAIL / REVIEW marker for validation check rows. */
export function CheckResultLabel({ result }: { result: string }) {
  const map: Record<string, { text: string; className: string; Icon: ComponentType<{ className?: string }> }> = {
    PASS: { text: "Pass", className: "text-success-text", Icon: CheckCircle2 },
    FAIL: { text: "Fail", className: "text-danger-text", Icon: XCircle },
    REVIEW: { text: "Review", className: "text-warning-text", Icon: AlertTriangle },
  };
  const spec = map[result] ?? map.REVIEW;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[13px] font-semibold ${spec.className}`}>
      <spec.Icon className="h-3.5 w-3.5 sm:hidden" aria-hidden="true" />
      {spec.text}
    </span>
  );
}
