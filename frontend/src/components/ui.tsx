import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  AlertTriangle, Check, Building2, CheckCircle2, ChevronDown, CircleAlert, ClipboardCheck, FileCheck2, FileText, FileWarning,
  Inbox, Loader2, Search, ShoppingCart, Stamp, X, XCircle, CircleCheck, Info,
} from 'lucide-react'
import { EVIDENCE_STATUS_LABEL, STATUS_TONE, progressTone, type Tone } from '../lib/format'
import type { EventItem } from '../lib/types'
import { fmtShort, fmtTime } from '../lib/format'

export function Chip({ tone, children, dot = true }: { tone: Tone; children: ReactNode; dot?: boolean }) {
  return <span className={`chip ${tone}${dot ? '' : ' no-dot'}`}>{children}</span>
}

export function StatusChip({ status, label }: { status: string; label?: string }) {
  return <Chip tone={STATUS_TONE[status] ?? 'gray'}>{label ?? status}</Chip>
}

export function EvidenceChip({ status }: { status: string }) {
  return <Chip tone={STATUS_TONE[status] ?? 'gray'}>{EVIDENCE_STATUS_LABEL[status] ?? status}</Chip>
}

export function Progress({ pct, status }: { pct: number; status: string }) {
  const tone = progressTone(pct, status)
  return (
    <div className="progress">
      <div className="progress-track">
        <div className={`progress-fill ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="progress-value">{pct}%</span>
    </div>
  )
}

export function Select({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label?: string
}) {
  return (
    <label className="select">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown size={15} />
    </label>
  )
}

export function SearchInput({ value, onChange, placeholder, filled, width }: {
  value: string; onChange: (v: string) => void; placeholder: string; filled?: boolean; width?: number
}) {
  return (
    <label className={`search-input${filled ? ' filled' : ''}`} style={width ? { width } : undefined}>
      <Search size={16} />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </label>
  )
}

export function Kpi({ icon, tone, value, label, pill }: { icon: ReactNode; tone: string; value: ReactNode; label: string; pill: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-top">
        <div className={`kpi-icon ${tone}`}>{icon}</div>
        <span className="kpi-pill">{pill}</span>
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  )
}

export function SrcTag({ children }: { children: ReactNode }) {
  return <span className="src-tag">{children}</span>
}

export function EvidenceIcon({ icon, size = 18 }: { icon: string; size?: number }) {
  switch (icon) {
    case 'cart': return <ShoppingCart size={size} />
    case 'clipboard': return <ClipboardCheck size={size} />
    case 'stamp': return <Stamp size={size} />
    case 'building': return <Building2 size={size} />
    default: return <FileText size={size} />
  }
}

export function EvidenceStatusIcon({ status, size = 20 }: { status: string; size?: number }) {
  if (status === 'MISSING') return <span className="ev-icon red"><FileWarning size={size} /></span>
  if (status === 'PENDING') return <span className="ev-icon gray"><Loader2 size={size} className="spin" /></span>
  if (status === 'NOT_REQUIRED') return <span className="ev-icon gray"><XCircle size={size} /></span>
  if (status === 'MANUALLY_UPLOADED') return <span className="ev-icon blue"><FileCheck2 size={size} /></span>
  return <span className="ev-icon"><FileCheck2 size={size} /></span>
}

export function Modal({ onClose, children, wide }: { onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true">{children}</div>
    </div>
  )
}

export function ActivityIcon({ type }: { type: EventItem['type'] }) {
  const size = 14
  const icon = type === 'success' ? <CircleCheck size={size} />
    : type === 'warning' ? <AlertTriangle size={size} />
    : type === 'error' ? <CircleAlert size={size} />
    : type === 'submit' ? <Inbox size={size} />
    : type === 'progress' ? <Loader2 size={size} /> : <Info size={size} />
  return <span className={`act-icon t-${type}`}>{icon}</span>
}

export function Activity({ events, limit = 6 }: { events: EventItem[]; limit?: number }) {
  if (!events.length) return <div className="muted">No activity yet.</div>
  return (
    <div className="activity">
      {events.slice(0, limit).map((e) => (
        <div className="act-item" key={e.id}>
          <ActivityIcon type={e.type} />
          <div>
            <div className="act-title">{e.title}</div>
            <div className="act-time">{fmtShort(e.created_at)} · {fmtTime(e.created_at)}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export function Stepper({ steps }: { steps: { label: string; state: string }[] }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div key={s.label} className={`step ${s.state}`}>
          {i < steps.length - 1 && <div className="step-line" />}
          <div className="step-dot">{s.state === 'done' ? <Check size={16} strokeWidth={3} /> : i + 1}</div>
          <div className="step-label">{s.label}</div>
        </div>
      ))}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="empty row" style={{ justifyContent: 'center' }}><Loader2 size={16} className="spin" /> {label}</div>
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card card-pad">
      <div className="alert error"><CircleAlert size={16} /> {message}</div>
      {onRetry && <button className="btn btn-outline mt-12" onClick={onRetry}>Try again</button>}
    </div>
  )
}

// ---- Toasts --------------------------------------------------------------------------------

type Toast = { id: number; tone: 'success' | 'error' | 'info'; text: string }
const ToastCtx = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone === 'info' ? '' : t.tone}`}>
            {t.tone === 'error' ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}
            <span style={{ flex: 1 }}>{t.text}</span>
            <X size={14} style={{ cursor: 'pointer', opacity: 0.8 }} onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} />
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)
