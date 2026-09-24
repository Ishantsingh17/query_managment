import { useNavigate } from 'react-router-dom'
import { CircleCheck, CircleX, ClipboardList, Hourglass, ShieldCheck } from 'lucide-react'
import { useApi } from '../lib/hooks'
import { fmtShort, fmtTime24 } from '../lib/format'
import type { Paged, RequestRow, Summary } from '../lib/types'
import { Kpi, Progress, StatusChip } from '../components/ui'

export default function ApprovalQueue() {
  const nav = useNavigate()
  const { data } = useApi<Paged<RequestRow>>('/api/requests?view=approvals&page_size=100&sort=created', { poll: 5000 })
  const { data: summary } = useApi<Summary>('/api/dashboard/summary', { poll: 10000 })
  const s = summary?.sme
  const rows = [...(data?.items ?? [])].sort((a, b) => (b.submitted_at ?? '').localeCompare(a.submitted_at ?? ''))

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Final Approval Queue</h1>
          <p className="page-sub">Review validated evidence packages and issue a final decision.</p>
        </div>
        {!!s?.awaiting && (
          <span className="attention purple"><ShieldCheck size={16} /> {s.awaiting} package{s.awaiting === 1 ? '' : 's'} awaiting your decision</span>
        )}
      </div>
      <div className="kpi-grid">
        <Kpi tone="purple" icon={<Hourglass size={18} />} value={s?.awaiting ?? '—'} label="Awaiting Approval" pill={`${s?.due_soon ?? 0} due soon`} />
        <Kpi tone="green" icon={<CircleCheck size={18} />} value={s?.approved ?? '—'} label="Approved" pill="this quarter" />
        <Kpi tone="red" icon={<CircleX size={18} />} value={s?.rejected ?? '—'} label="Rejected" pill="sent to rework" />
        <Kpi tone="blue" icon={<ClipboardList size={18} />} value={s?.total_reviewed ?? '—'} label="Total Reviewed" pill={`avg ${s?.avg_days ?? 0} days`} />
      </div>
      <div className="card table-card">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr><th>Request ID</th><th>Query Type</th><th>Validation</th><th>Completeness</th><th>Created</th><th>Submitted</th><th>Status</th><th className="right">Action</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.request_id} className={`clickable${i === 0 ? ' highlight' : ''}`} onClick={() => nav(`/approvals/${r.request_id}`)}>
                  <td className="id-link">{r.request_id}</td>
                  <td>{r.query_type_label}</td>
                  <td><span className="text-green row gap-4"><CircleCheck size={16} /> Validated</span></td>
                  <td style={{ width: '17%' }}><Progress pct={r.completeness_pct} status={r.status} /></td>
                  <td className="muted">{fmtShort(r.created_at)}</td>
                  <td className="muted">{fmtShort(r.submitted_at)} · {fmtTime24(r.submitted_at)}</td>
                  <td><StatusChip status="SME_REVIEW" label="SME Review" /></td>
                  <td className="right">
                    <button className={`btn ${i === 0 ? 'btn-dark' : 'btn-outline'}`} onClick={(e) => { e.stopPropagation(); nav(`/approvals/${r.request_id}`) }}>
                      Review Package
                    </button>
                  </td>
                </tr>
              ))}
              {data && !rows.length && <tr><td colSpan={8}><div className="empty">No packages are awaiting your decision.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
