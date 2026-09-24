import { Fragment, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Check, ChevronRight, ExternalLink, PackageCheck } from 'lucide-react'
import { openFile } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/hooks'
import { ACTIVE_STATES, fmtDate, fmtTime } from '../lib/format'
import type { RequestDetail as Detail } from '../lib/types'
import { Activity, Chip, ErrorState, EvidenceChip, EvidenceStatusIcon, Loading, StatusChip, Stepper, useToast } from '../components/ui'
import StatusDrawer from '../components/StatusDrawer'

export default function RequestDetail() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const { user } = useAuth()
  const [drawer, setDrawer] = useState(false)
  const { data: d, error, refresh } = useApi<Detail>(`/api/requests/${id}`, { poll: 5000 })

  if (error) return <ErrorState message={error.message} onRetry={refresh} />
  if (!d) return <Loading />

  const c = d.counts
  const available = c ? c.available + c.manual : 0
  const done = ['COMPLETED', 'NOTIFIED'].includes(d.status)

  return (
    <>
      <div className="crumbs">
        <Link to={user?.role === 'AUDITOR' ? '/requests' : '/dashboard'}>Requests</Link>
        <ChevronRight size={14} />
        <strong>{d.request_id}</strong>
      </div>

      {done && user?.role === 'AUDITOR' && (
        <div className="banner green">
          <PackageCheck size={18} /> The Final Response Package is ready.
          <button className="btn btn-success btn-sm" style={{ marginLeft: 'auto' }} onClick={() => nav(`/requests/${d.request_id}/final`)}>Open Final Response</button>
        </div>
      )}

      <div className="card card-pad" style={{ padding: '22px 22px 24px' }}>
        <div className="between" style={{ alignItems: 'flex-start' }}>
          <div>
            <div className="row gap-12">
              <h2 style={{ fontSize: 21 }}>{d.request_id}</h2>
              <StatusChip status={d.status} label={d.status_label} />
            </div>
            <div className="muted mt-8" style={{ fontSize: 13.5 }}>
              {d.query_type_label} · Created {fmtDate(d.created_at)} · {fmtTime(d.created_at)} by {d.auditor_name}
            </div>
          </div>
          <div className="row gap-8">
            <button className="btn btn-outline btn-lg" onClick={() => setDrawer(true)}>View Timeline</button>
            <button className="btn btn-primary btn-lg" onClick={async () => { await refresh(); toast('Status refreshed.') }}>Refresh Status</button>
          </div>
        </div>
        <div className="quote-box mt-20">
          <div className="eyebrow" style={{ marginBottom: 6 }}>Original auditor request</div>
          “{d.original_query}”
        </div>
        <Stepper steps={d.stepper} />
      </div>

      <div className="grid-main-side mt-20" style={{ gridTemplateColumns: 'minmax(0,1fr) 400px' }}>
        <div className="card card-pad">
          <div className="between">
            <div className="card-title">Evidence summary</div>
            {c && <strong>{available} of {c.required} available</strong>}
          </div>
          {ACTIVE_STATES.has(d.status) && !d.evidence.length && <Loading label="Classifying request and planning retrieval…" />}
          {c && (
            <div className="count-tiles">
              <div className="count-tile"><div className="n" style={{ color: 'var(--navy-900)' }}>{c.required}</div><div className="l">Required</div></div>
              <div className="count-tile"><div className="n" style={{ color: 'var(--green-700)' }}>{c.available}</div><div className="l">Available</div></div>
              <div className="count-tile"><div className="n" style={{ color: 'var(--red-700)' }}>{c.missing}</div><div className="l">Missing</div></div>
              <div className="count-tile"><div className="n" style={{ color: 'var(--blue-600)' }}>{c.manual}</div><div className="l">Manual</div></div>
              <div className="count-tile"><div className="n" style={{ color: 'var(--ink-400)' }}>{c.not_required}</div><div className="l">Not required</div></div>
            </div>
          )}
          <div className="mt-8">
            {d.evidence.map((e) => (
              <div className="evidence-row" key={e.evidence_type}>
                <EvidenceStatusIcon status={e.status} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ev-name">{e.label}</div>
                  <div className="ev-meta">
                    {e.status === 'MISSING' ? (e.reason ?? `${e.source_system} · not retrieved`)
                      : e.status === 'NOT_REQUIRED' ? `Accepted as not required · ${e.justification ?? ''}`
                      : e.status === 'PENDING' ? e.evidence_description
                      : [e.source_system, e.source_reference].filter(Boolean).join(' · ')}
                  </div>
                </div>
                {e.has_file && e.evidence_id && (
                  <button className="link-btn" onClick={() => openFile(`/api/evidence/${e.evidence_id}/file`)}>Open <ExternalLink size={13} /></button>
                )}
                <EvidenceChip status={e.status} />
              </div>
            ))}
          </div>
          {user?.role === 'AUDITOR' && !done && d.evidence.some((e) => e.status !== 'PENDING') && (
            <div className="hint mt-12">Evidence files become available to auditors once the SME approves the package.</div>
          )}
        </div>
        <div className="stack gap-16">
          {d.understanding && (
            <div className="card card-pad understanding">
              <div className="eyebrow">Request understanding</div>
              <dl className="u-list">
                <dt>Query Type</dt><dd>{d.understanding.query_type_label}</dd>
                {d.understanding.parameters.map((p) => <Fragment key={p.param}><dt>{p.label}</dt><dd>{p.value}</dd></Fragment>)}
                {d.understanding.period && <><dt>Period</dt><dd>{d.understanding.period}</dd></>}
              </dl>
              <div className="u-sub">Evidence requested</div>
              <ul className="u-check">
                {d.understanding.evidence_requested.map((e) => <li key={e.evidence_type}><Check size={14} /> {e.label}</li>)}
              </ul>
              <div className="u-status">
                <div><span className="muted">Parameter status</span>
                  <Chip tone={d.understanding.parameter_status === 'COMPLETE' ? 'green' : 'amber'}>
                    {d.understanding.parameter_status === 'COMPLETE' ? 'Complete' : 'Action required'}
                  </Chip>
                </div>
                <div><span className="muted">Retrieval status</span><StatusChip status={d.status} label={d.status_label} /></div>
              </div>
            </div>
          )}
          <div className="card card-pad">
            <div className="card-title" style={{ marginBottom: 16 }}>Activity</div>
            <Activity events={d.events} limit={7} />
          </div>
        </div>
      </div>
      {drawer && <StatusDrawer requestId={d.request_id} onClose={() => setDrawer(false)} />}
    </>
  )
}
