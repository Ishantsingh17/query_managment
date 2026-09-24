import { Link } from 'react-router-dom'
import { Download } from 'lucide-react'
import { download } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/hooks'
import type { Paged, RequestRow } from '../lib/types'
import { Chip, Loading } from '../components/ui'

function Bars({ data }: { data: [string, number][] }) {
  const max = Math.max(1, ...data.map(([, v]) => v))
  return (
    <div className="bar-chart">
      {data.map(([k, v]) => (
        <div className="b-row" key={k}>
          <span>{k}</span>
          <div className="b-track"><div className="b-fill" style={{ width: `${(v / max) * 100}%` }} /></div>
          <strong style={{ textAlign: 'right' }}>{v}</strong>
        </div>
      ))}
    </div>
  )
}

export function Reports() {
  const { data } = useApi<Paged<RequestRow>>('/api/requests?view=all&page_size=100')
  if (!data) return <Loading />
  const count = (key: (r: RequestRow) => string) =>
    Object.entries(data.items.reduce<Record<string, number>>((acc, r) => ({ ...acc, [key(r)]: (acc[key(r)] ?? 0) + 1 }), {}))
      .sort((a, b) => b[1] - a[1])
  const missing = count((r) => (r.missing_evidence.length ? 'Has missing evidence' : 'Complete')).filter(([k]) => k)
  const avg = data.items.length ? Math.round(data.items.reduce((s, r) => s + r.completeness_pct, 0) / data.items.length) : 0
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Reports</h1>
          <p className="page-sub">Portfolio view of request volume, workflow stage and evidence completeness.</p>
        </div>
        <button className="btn btn-outline btn-lg" onClick={() => download('/api/requests/export.csv?view=dashboard')}><Download size={17} /> Export CSV</button>
      </div>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="card kpi"><div className="kpi-label">Requests in scope</div><div className="kpi-value">{data.total}</div></div>
        <div className="card kpi"><div className="kpi-label">Average evidence completeness</div><div className="kpi-value">{avg}%</div></div>
        <div className="card kpi"><div className="kpi-label">Requests with missing evidence</div><div className="kpi-value">{missing.find(([k]) => k === 'Has missing evidence')?.[1] ?? 0}</div></div>
      </div>
      <div className="grid-main-side" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card card-pad"><div className="card-title" style={{ marginBottom: 16 }}>By workflow status</div><Bars data={count((r) => r.status_label)} /></div>
        <div className="card card-pad"><div className="card-title" style={{ marginBottom: 16 }}>By query type</div><Bars data={count((r) => r.query_type_label)} /></div>
      </div>
    </>
  )
}

export function SettingsPage() {
  const { user } = useAuth()
  const { data: status } = useApi<{ sources: { source_system: string; available: boolean }[] }>('/api/system/status', { poll: 15000 })
  if (!user) return null
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">Your profile, notification preferences and connected source systems.</p>
        </div>
      </div>
      <div className="grid-main-side" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card card-pad">
          <div className="card-title" style={{ marginBottom: 16 }}>Profile</div>
          <dl className="kv">
            <dt>Name</dt><dd>{user.full_name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.title}</dd>
            <dt>Notifications</dt><dd>Email with application link (Gmail) when {user.role === 'SME' ? 'a review package is ready' : user.role === 'AUDITOR' ? 'your Final Response Package is ready' : 'requests need validation'}</dd>
          </dl>
        </div>
        <div className="card card-pad">
          <div className="card-title" style={{ marginBottom: 16 }}>Connected source systems</div>
          <div className="stack gap-8">
            {status?.sources.map((s) => (
              <div className="between" key={s.source_system} style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                <strong>{s.source_system}</strong>
                {s.available ? <Chip tone="green">Connected</Chip> : <Chip tone="red">Unavailable</Chip>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

const FAQ: [string, string][] = [
  ['How do I request evidence?', 'Open Create Request and describe what you need in plain language. The platform shows what it understood (Query Type, identifiers, evidence) and asks for any missing detail, such as a Payment Document Number, before retrieval starts.'],
  ['What decides which evidence is required?', 'Each query type maps to a controlled list of required evidence in the Requirement Catalog. Source systems are chosen from the Evidence Source Registry — never guessed.'],
  ['What happens when evidence is missing?', 'A Human Validator can retry retrieval, upload the evidence manually, or accept the item as not required with a justification. The request then continues to SME approval.'],
  ['Who approves the package?', 'The Final Approver (SME) reviews the Evidence Review Package and approves or rejects it. A comment is mandatory when rejecting.'],
  ['When can I open the evidence files?', 'Auditors can open evidence once the SME approves the package; the Final Response Package contains only approved evidence.'],
  ['Where do notifications go?', 'Validators are emailed when evidence is missing, SMEs when a package is ready, and auditors when the Final Response Package is approved. Every link opens the sign-in page first and then takes you to the request.'],
]

export function Help() {
  const { data: types } = useApi<{ value: string; label: string; evidence_required: string; automation_behavior: string }[]>('/api/requests/query-types')
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Help Center</h1>
          <p className="page-sub">Answers to common questions about the audit evidence workflow.</p>
        </div>
      </div>
      <div className="card card-pad faq">
        <details open>
          <summary>Which Query Types are supported?</summary>
          {(types ?? []).map((t) => (
            <p key={t.value}><strong>{t.label}</strong> — evidence: {t.evidence_required}.<br />
              <span className="muted">Automated: {t.automation_behavior}.</span></p>
          ))}
        </details>
        {FAQ.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}
        <p className="muted mt-16">Still stuck? Contact IT support or your audit platform administrator.</p>
      </div>
    </>
  )
}

export function NotFound() {
  return (
    <div className="card card-pad" style={{ maxWidth: 520 }}>
      <h2 style={{ fontSize: 18 }}>Page not found</h2>
      <p className="muted">The page you're looking for doesn't exist or you don't have access to it.</p>
      <Link className="btn btn-primary mt-12" to="/">Go to home</Link>
    </div>
  )
}
