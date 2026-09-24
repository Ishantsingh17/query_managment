import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Calendar, Check, ChevronDown, ChevronRight, CircleAlert, Clock, Lightbulb, Loader2, Send, Sparkles, X,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { useApi } from '../lib/hooks'
import { timeAgo } from '../lib/format'
import type { Summary, Understanding } from '../lib/types'
import { Chip, useToast } from '../components/ui'
import { useQueryTypeOptions } from './Dashboard'

const DRAFT_KEY = 'aep.request-draft'

type Ids = Record<string, string>
interface Draft { query: string; ids: Ids; date_from: string; date_to: string; query_type: string }
interface Message { id: number; role: 'auditor' | 'system'; text: string; understanding?: Understanding }

const EMPTY: Draft = { query: '', ids: {}, date_from: '', date_to: '', query_type: '' }
const ID_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: 'payment_document_number', label: 'Payment Document Number', placeholder: 'e.g. 1900004533' },
  { key: 'invoice_number', label: 'Invoice Number', placeholder: 'e.g. INV-2026-08560' },
  { key: 'po_number', label: 'PO Number', placeholder: 'e.g. 4500239012' },
  { key: 'vendor_id', label: 'Vendor ID', placeholder: 'e.g. 1004821' },
  { key: 'employee_id', label: 'Employee ID', placeholder: 'e.g. E-20413' },
  { key: 'fiscal_year', label: 'Fiscal Year', placeholder: 'e.g. 2026' },
]
const RETRIEVAL_LABEL: Record<string, string> = {
  READY: 'Ready to retrieve', WAITING_FOR_PARAMETERS: 'Waiting for details', NEEDS_CLARIFICATION: 'Needs clarification',
  UNSUPPORTED: 'Not supported',
}

function loadDraft(): { draft: Draft; savedAt: number | null } {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed?.draft?.ids) return { draft: { ...EMPTY, ...parsed.draft }, savedAt: parsed.savedAt ?? null }
    }
  } catch { /* ignore */ }
  return { draft: EMPTY, savedAt: null }
}

export default function CreateRequest() {
  const nav = useNavigate()
  const toast = useToast()
  const initial = useMemo(loadDraft, [])
  const [f, setF] = useState<Draft>(initial.draft)
  const [savedAt, setSavedAt] = useState<number | null>(initial.savedAt)
  const [thread, setThread] = useState<Message[]>([])
  const [understanding, setUnderstanding] = useState<Understanding | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showIds, setShowIds] = useState(false)
  const [, tick] = useState(0)
  const threadEnd = useRef<HTMLDivElement>(null)
  const qtOptions = useQueryTypeOptions('Auto-detect from request')
  const { data: summary } = useApi<Summary & { auditor: { median_turnaround_days?: number } }>('/api/dashboard/summary')

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (f === initial.draft) return
      try {
        const now = Date.now()
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ draft: f, savedAt: now }))
        setSavedAt(now)
      } catch { /* storage unavailable */ }
    }, 500)
    return () => window.clearTimeout(t)
  }, [f, initial.draft])
  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 30000)
    return () => window.clearInterval(id)
  }, [])
  useEffect(() => { threadEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [thread])

  const say = (role: Message['role'], text: string, u?: Understanding) =>
    setThread((t) => [...t, { id: Date.now() + Math.random(), role, text, understanding: u }])

  const payload = (d: Draft) => ({
    query: d.query.trim(), query_type: d.query_type || null, date_from: d.date_from || null, date_to: d.date_to || null,
    identifiers: Object.fromEntries(Object.entries(d.ids).filter(([, v]) => v.trim())),
  })

  const analyze = async (d: Draft, auditorText?: string) => {
    if (d.query.trim().length < 5) {
      setError('Describe the evidence you need to get started.')
      return
    }
    setError(null)
    if (auditorText) say('auditor', auditorText)
    setAnalyzing(true)
    try {
      const u = await api.post<Understanding>('/api/requests/analyze', payload(d))
      setUnderstanding(u)
      say('system', u.message, u)
    } catch (e) {
      setError((e as ApiError).message)
    } finally {
      setAnalyzing(false)
    }
  }

  const send = () => {
    setThread([])
    analyze(f, f.query.trim())
  }

  const supplyParams = (values: Ids) => {
    const next = { ...f, ids: { ...f.ids, ...values } }
    setF(next)
    const text = Object.entries(values).map(([k, v]) => `${ID_FIELDS.find((x) => x.key === k)?.label ?? k}: ${v}`).join(' · ')
    analyze(next, text)
  }

  const chooseType = (value: string, label: string) => {
    const next = { ...f, query_type: value }
    setF(next)
    analyze(next, `I need ${label}.`)
  }

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.post<{ request_id: string }>('/api/requests', payload(f))
      try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
      toast(`Request ${res.request_id} submitted — retrieval has started.`, 'success')
      nav(`/requests/${res.request_id}`)
    } catch (e) {
      const err = e as ApiError & { details?: Understanding }
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setF(EMPTY)
    setThread([])
    setUnderstanding(null)
    setError(null)
    try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  }

  const latestSystem = [...thread].reverse().find((m) => m.role === 'system')
  const median = summary?.auditor?.median_turnaround_days

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Create Audit Request</h1>
          <p className="page-sub">Describe what you need in plain language. The platform identifies the Query Type and asks for anything it still needs.</p>
        </div>
      </div>

      <div className="grid-main-side" style={{ gridTemplateColumns: 'minmax(0,1fr) 340px' }}>
        <div className="card card-pad" style={{ padding: '22px 20px' }}>
          <div className="between" style={{ marginBottom: 14 }}>
            <div className="card-title">Audit request</div>
            <span className="badge-soft">Natural language enabled</span>
          </div>

          {/* Conversation */}
          <div className="chat">
            <div className="bubble system">
              Describe the evidence you need — for example the Query Type, document numbers and period. I'll check the
              required evidence and ask for any missing details before retrieval starts.
            </div>
            {thread.map((m) => (
              <div key={m.id} className={`bubble ${m.role}`}>
                {m.role === 'system' && <Sparkles size={14} className="bubble-icon" />}
                <span>{m.text}</span>
                {m === latestSystem && m.understanding && !analyzing && (
                  <SystemActions u={m.understanding} submitting={submitting} onSupply={supplyParams}
                                 onChoose={chooseType} onSubmit={submit} />
                )}
              </div>
            ))}
            {analyzing && <div className="bubble system"><Loader2 size={14} className="spin" /> Analysing your request…</div>}
            <div ref={threadEnd} />
          </div>

          {/* Composer */}
          <div className="composer mt-16">
            <textarea className="textarea composer-input" rows={3} value={f.query} aria-label="Audit request"
                      onChange={(e) => setF({ ...f, query: e.target.value })}
                      onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send() }}
                      placeholder="e.g. Retrieve payment testing evidence for payment document 1900004533 for August 2026, including invoice, purchase order, goods receipt and payment approval." />
            <div className="between composer-bar">
              <div className="row gap-8" style={{ flexWrap: 'wrap' }}>
                <div className="select">
                  <select value={f.query_type} onChange={(e) => setF({ ...f, query_type: e.target.value })} aria-label="Query type">
                    {qtOptions.map((o) => <option key={o.value} value={o.value}>{o.value ? o.label : 'Query type: Auto-detect'}</option>)}
                  </select>
                  <ChevronDown size={15} />
                </div>
                <button type="button" className="link-btn" onClick={() => setShowIds(!showIds)}>
                  {showIds ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Known identifiers (optional)
                </button>
              </div>
              <div className="row gap-8">
                {thread.length > 0 && <button className="btn btn-outline" onClick={reset}><X size={15} /> Clear</button>}
                <button className="btn btn-primary" onClick={send} disabled={analyzing || !f.query.trim()}>
                  <Send size={15} /> {thread.length ? 'Re-analyse' : 'Analyse request'}
                </button>
              </div>
            </div>
            {showIds && (
              <div className="form-grid mt-12">
                {ID_FIELDS.map((fld) => (
                  <div className="field" key={fld.key}>
                    <label className="label" htmlFor={fld.key}>{fld.label}</label>
                    <input id={fld.key} className="input" placeholder={fld.placeholder} value={f.ids[fld.key] ?? ''}
                           onChange={(e) => setF({ ...f, ids: { ...f.ids, [fld.key]: e.target.value } })} />
                  </div>
                ))}
                <div className="field">
                  <span className="label">Date range</span>
                  <div className="input-group" style={{ height: 38 }}>
                    <input type="date" aria-label="From date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
                    <span className="muted">–</span>
                    <input type="date" aria-label="To date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
                    <Calendar size={16} />
                  </div>
                </div>
              </div>
            )}
          </div>
          {error && <div className="alert error mt-12"><CircleAlert size={16} /> {error}</div>}
          <div className="between mt-12">
            <span className="hint">Ctrl + Enter to analyse. Identifiers in your text are picked up automatically.</span>
            {savedAt && <span className="muted">Draft saved {timeAgo(savedAt)}</span>}
          </div>
        </div>

        <div className="stack gap-16">
          <UnderstandingPanel u={understanding} />
          <div className="card card-pad">
            <div className="card-title" style={{ marginBottom: 12 }}>What happens next</div>
            {['Evidence retrieved from connected systems', 'Completeness checked & validated', 'SME reviews & approves package'].map((t, i) => (
              <div key={t} className="row gap-12" style={{ marginBottom: 12, color: 'var(--ink-600)' }}>
                <span className="step-num">{i + 1}</span>{t}
              </div>
            ))}
            <div className="row gap-8" style={{ background: 'var(--tile)', borderRadius: 8, padding: '10px 12px', fontWeight: 500 }}>
              <Clock size={16} color="#1d56db" /> Median turnaround: {median ? `${median} days` : '—'}
            </div>
          </div>
          <div className="card card-pad" style={{ background: 'var(--navy-900)', color: '#fff', border: 0 }}>
            <div className="row gap-8" style={{ fontWeight: 700, fontSize: 14 }}><Lightbulb size={17} /> Tips for better results</div>
            <p style={{ color: '#d6deec', margin: '10px 0 0', lineHeight: 1.6 }}>
              Name the test (e.g. payment testing, balance confirmation) and include the document number, vendor or invoice
              and the period. You'll be asked for anything that is still missing.
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

function SystemActions({ u, submitting, onSupply, onChoose, onSubmit }: {
  u: Understanding; submitting: boolean
  onSupply: (v: Ids) => void; onChoose: (value: string, label: string) => void; onSubmit: () => void
}) {
  const [values, setValues] = useState<Ids>({})
  const [useAlt, setUseAlt] = useState<Record<string, string>>({})
  if (u.retrieval_status === 'WAITING_FOR_PARAMETERS') {
    const fields = u.missing_parameters.map((m) => {
      const key = useAlt[m.param] ?? m.param
      const label = key === m.param ? m.label : m.alternatives.find((a) => a.param === key)?.label ?? key
      return { m, key, label }
    })
    const ready = fields.every(({ key }) => (values[key] ?? '').trim())
    return (
      <form className="bubble-actions" onSubmit={(e) => { e.preventDefault(); if (ready) onSupply(Object.fromEntries(fields.map(({ key }) => [key, values[key].trim()]))) }}>
        {fields.map(({ m, key, label }) => (
          <div className="field" key={m.param}>
            <label className="label" htmlFor={`ask-${key}`}>{label}</label>
            <input id={`ask-${key}`} className="input" autoFocus value={values[key] ?? ''}
                   onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
            {m.alternatives.length > 0 && (
              <button type="button" className="link-btn" style={{ fontSize: 12, fontWeight: 500 }}
                      onClick={() => setUseAlt({ ...useAlt, [m.param]: key === m.param ? m.alternatives[0].param : m.param })}>
                or enter {key === m.param ? m.alternatives[0].label : m.label} instead
              </button>
            )}
          </div>
        ))}
        <button className="btn btn-primary" type="submit" disabled={!ready}>Continue</button>
      </form>
    )
  }
  if (u.retrieval_status === 'NEEDS_CLARIFICATION') {
    return (
      <div className="bubble-actions row gap-8" style={{ flexWrap: 'wrap' }}>
        {u.candidates.map((c) => <button key={c.value} className="btn btn-outline btn-sm" onClick={() => onChoose(c.value, c.label)}>{c.label}</button>)}
      </div>
    )
  }
  if (u.retrieval_status === 'UNSUPPORTED') {
    return (
      <div className="bubble-actions">
        <div className="hint" style={{ marginBottom: 6 }}>Rephrase your request, or choose one of the supported Query Types:</div>
        <div className="row gap-8" style={{ flexWrap: 'wrap' }}>
          {u.supported_query_types.map((c) => <button key={c.value} className="btn btn-outline btn-sm" onClick={() => onChoose(c.value, c.label)}>{c.label}</button>)}
        </div>
      </div>
    )
  }
  return (
    <div className="bubble-actions">
      <button className="btn btn-primary" onClick={onSubmit} disabled={submitting}>
        <Send size={15} /> {submitting ? 'Submitting…' : 'Submit request'}
      </button>
    </div>
  )
}

function UnderstandingPanel({ u }: { u: Understanding | null }) {
  if (!u) {
    return (
      <div className="card card-pad understanding">
        <div className="eyebrow">Request understanding</div>
        <p className="muted" style={{ margin: '10px 0 0', lineHeight: 1.55 }}>
          Analyse your request to see the Query Type, the parameters picked up and the evidence that will be retrieved.
        </p>
      </div>
    )
  }
  const params = u.parameters.filter((p) => !p.param.startsWith('period_'))
  const statusTone = u.retrieval_status === 'READY' ? 'green' : u.retrieval_status === 'UNSUPPORTED' ? 'red' : 'amber'
  return (
    <div className="card card-pad understanding">
      <div className="eyebrow">Request understanding</div>
      <dl className="u-list">
        <dt>Query Type</dt>
        <dd>{u.query_type_label ?? (u.retrieval_status === 'NEEDS_CLARIFICATION' ? 'Needs clarification' : 'Not supported')}</dd>
        {params.map((p) => <FragmentRow key={p.param} label={p.label} value={p.value} />)}
        {u.period && <FragmentRow label="Period" value={u.period} />}
      </dl>
      {u.evidence_requested.length > 0 && (
        <>
          <div className="u-sub">Evidence requested</div>
          <ul className="u-check">
            {u.evidence_requested.map((e) => <li key={e.evidence_type} title={e.description}><Check size={14} /> {e.label}</li>)}
          </ul>
        </>
      )}
      {u.required_parameters.length > 0 && (
        <>
          <div className="u-sub">Required parameters</div>
          <ul className="u-check">
            {u.required_parameters.map((p) => (
              <li key={p.label} className={p.satisfied ? '' : 'missing'}>
                {p.satisfied ? <Check size={14} /> : <CircleAlert size={14} />} {p.label}{p.value ? ` · ${p.value}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="u-status">
        <div><span className="muted">Parameter status</span>
          {u.parameter_status === 'NOT_APPLICABLE' ? <span className="muted">—</span>
            : <Chip tone={u.parameter_status === 'COMPLETE' ? 'green' : 'amber'}>{u.parameter_status === 'COMPLETE' ? 'Complete' : 'Action required'}</Chip>}
        </div>
        {u.missing_parameters.length > 0 && (
          <div><span className="muted">Missing</span><strong className="text-red" style={{ textAlign: 'right' }}>{u.missing_parameters.map((m) => m.label).join(', ')}</strong></div>
        )}
        <div><span className="muted">Retrieval status</span><Chip tone={statusTone}>{RETRIEVAL_LABEL[u.retrieval_status]}</Chip></div>
      </div>
    </div>
  )
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>
}
