const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** Aug 18, 2026 */
export function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${MONTHS[d.getMonth()]} ${pad(d.getDate())}, ${d.getFullYear()}`
}

/** Aug 18 */
export function fmtShort(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${MONTHS[d.getMonth()]} ${pad(d.getDate())}`
}

/** 09:42 AM */
export function fmtTime(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const h = d.getHours() % 12 || 12
  return `${pad(h)}:${pad(d.getMinutes())} ${d.getHours() < 12 ? 'AM' : 'PM'}`
}

/** 09:10 (24h) */
export function fmtTime24(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export function timeAgo(ms: number): string {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  return `${h} hr ago`
}

export type Tone = 'blue' | 'purple' | 'green' | 'amber' | 'red' | 'gray'

export const STATUS_TONE: Record<string, Tone> = {
  REQUEST_CREATED: 'blue',
  PROCESSING: 'blue',
  VALIDATION_PENDING: 'amber',
  REWORK_REQUIRED: 'red',
  REVIEW_READY: 'green',
  SME_REVIEW: 'purple',
  APPROVED: 'green',
  REJECTED: 'red',
  FINAL_RESPONSE_READY: 'green',
  NOTIFIED: 'green',
  COMPLETED: 'green',
  AVAILABLE: 'green',
  MANUALLY_UPLOADED: 'blue',
  NOT_REQUIRED: 'gray',
  MISSING: 'red',
  PENDING: 'gray',
}

export const EVIDENCE_STATUS_LABEL: Record<string, string> = {
  AVAILABLE: 'Available',
  MISSING: 'Missing',
  MANUALLY_UPLOADED: 'Manually Uploaded',
  NOT_REQUIRED: 'Not Required',
  PENDING: 'Retrieving…',
}

export function progressTone(pct: number, status: string): 'green' | 'blue' | 'red' {
  if (pct >= 100) return 'green'
  if (status === 'REWORK_REQUIRED' || status === 'REJECTED') return 'red'
  return 'blue'
}

export const ACTIVE_STATES = new Set(['REQUEST_CREATED', 'PROCESSING'])
