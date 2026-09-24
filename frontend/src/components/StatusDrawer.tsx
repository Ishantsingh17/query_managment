import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity as ActivityIcon, AlertTriangle, Check, Clock, X, CircleAlert } from 'lucide-react'
import { download } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/hooks'
import { ACTIVE_STATES, fmtShort, fmtTime } from '../lib/format'
import type { EventItem, RequestDetail } from '../lib/types'
import { StatusChip } from './ui'

/** Milestone events shown in the live status drawer (the Activity panel shows everything). */
const MILESTONES = [/^Request submitted/, /^Processing completed/, /^Retry completed/, /^Processing interrupted/, /^Completeness check/,
  /uploaded manually$/, /accepted as not required$/, /^Validation finished/, /^Review package ready/, /^SME review in progress/,
  /^Package (approved|rejected)/, /^Returned to validation/, /^Final Response Package sealed/, /^Final package generation failed/,
  /^Auditor notified/, /^Request completed/, /^Retry \/ rework started/]

export default function StatusDrawer({ requestId, onClose }: { requestId: string; onClose: () => void }) {
  const nav = useNavigate()
  const { user } = useAuth()
  const { data: d } = useApi<RequestDetail>(`/api/requests/${requestId}`, { poll: 4000 })
  const { data: events } = useApi<EventItem[]>(`/api/requests/${requestId}/events`, { poll: 4000 })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const items = (events ?? []).filter((e) => MILESTONES.some((m) => m.test(e.title)))
  const done = d && !ACTIVE_STATES.has(d.status) && ['COMPLETED', 'NOTIFIED'].includes(d.status)
  const fullPath = user?.role === 'VALIDATOR' ? `/queue/${requestId}` : user?.role === 'SME' ? `/approvals/${requestId}` : `/requests/${requestId}`
  const docNo = d?.parameters?.payment_document_number
  const idLine = docNo ? `Payment doc ${docNo}` : d?.parameters?.po_number ? `PO ${d.parameters.po_number}`
    : d?.parameters?.vendor_id ? `Vendor ${d.parameters.vendor_id}` : d?.parameters?.employee_id ? `Employee ${d.parameters.employee_id}` : ''

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Request status">
        <div className="drawer-head">
          <div>
            <div className="row gap-8">
              <h3 style={{ fontSize: 17 }}>{requestId}</h3>
              {d && <StatusChip status={d.status} label={d.status_label} />}
            </div>
            <div className="muted mt-4" style={{ fontSize: 13 }}>{d?.query_type_label}{idLine ? ` · ${idLine}` : ''}</div>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="drawer-live">
          <ActivityIcon size={16} color="#1d56db" style={{ marginTop: 1, flex: 'none' }} />
          <span>{done ? 'Final status — this request has completed its workflow.' : 'Live status — refreshes automatically as the workflow advances.'}</span>
        </div>
        <div className="drawer-body">
          <div className="timeline">
            {items.map((e, i) => {
              const isLast = i === items.length - 1
              const current = isLast && !done && e.type === 'progress'
              const cls = e.type === 'error' ? 'err' : e.type === 'warning' ? 'warn' : current ? 'current' : ''
              return (
                <div className={`tl-item${current ? ' pending' : ''}`} key={e.id}>
                  <div className={`tl-dot ${cls}`}>
                    {cls === 'err' ? <CircleAlert size={14} /> : cls === 'warn' ? <AlertTriangle size={13} /> : current ? <Clock size={14} /> : <Check size={14} strokeWidth={3} />}
                  </div>
                  <div>
                    <div className="tl-title">{e.title}</div>
                    <div className="tl-meta">{[e.actor_name, e.actor_role].filter(Boolean).join(' · ')}{e.actor_name ? ' · ' : ''}{fmtShort(e.created_at)} · {fmtTime(e.created_at)}</div>
                    {e.detail && <div className="tl-detail">{e.detail}</div>}
                  </div>
                </div>
              )
            })}
            {!items.length && <div className="muted">Loading status…</div>}
          </div>
        </div>
        <div className="drawer-foot">
          <button className="btn btn-outline" onClick={() => download(`/api/requests/${requestId}/trail.csv`)}>Download trail</button>
          <button className="btn btn-dark" onClick={() => { onClose(); nav(fullPath) }}>Open full request</button>
        </div>
      </aside>
    </>
  )
}
