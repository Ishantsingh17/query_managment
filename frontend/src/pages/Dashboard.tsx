import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown, ChevronLeft, ChevronRight, CircleCheck, Clock, Files, Loader, Plus } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/hooks'
import { fmtDate, greeting } from '../lib/format'
import type { Paged, RequestRow, Summary } from '../lib/types'
import { Kpi, Progress, SearchInput, Select, StatusChip } from '../components/ui'
import StatusDrawer from '../components/StatusDrawer'
import DashboardCharts from '../components/DashboardCharts'

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'REQUEST_CREATED,PROCESSING', label: 'Processing' },
  { value: 'VALIDATION_PENDING', label: 'Validation Pending' },
  { value: 'REWORK_REQUIRED', label: 'Rework Required' },
  { value: 'REVIEW_READY', label: 'Review Ready' },
  { value: 'SME_REVIEW', label: 'SME Review' },
  { value: 'NOTIFIED,COMPLETED', label: 'Completed' },
]
const PERIOD_OPTIONS = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'last_90', label: 'Last 90 days' },
  { value: 'all', label: 'All time' },
]

export function useQueryTypeOptions(allLabel: string) {
  const { data } = useApi<{ value: string; label: string }[]>('/api/requests/query-types')
  return [{ value: '', label: allLabel }, ...(data ?? [])]
}

/** Auditor dashboard (screen 02). Also used as the "Requests" grid and SME/validator portfolio view. */
export default function Dashboard({ mode = 'dashboard' }: { mode?: 'dashboard' | 'requests' }) {
  const { user } = useAuth()
  const nav = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [queryType, setQueryType] = useState('')
  const [period, setPeriod] = useState(mode === 'dashboard' ? 'this_month' : 'all')
  const [sort, setSort] = useState<'updated' | 'created'>('updated')
  const [page, setPage] = useState(1)
  const [drawer, setDrawer] = useState<string | null>(null)
  const qtOptions = useQueryTypeOptions('All query types')

  const params = new URLSearchParams({ view: user?.role === 'AUDITOR' ? 'dashboard' : 'all', page: String(page), page_size: mode === 'dashboard' ? '6' : '10', period, sort })
  if (status) params.set('status', status)
  if (queryType) params.set('query_type', queryType)
  if (search.trim()) params.set('search', search.trim())
  // Auditor dashboard shows insight charts instead of the request table (the table lives on the Requests page).
  const showCharts = mode === 'dashboard' && user?.role === 'AUDITOR'
  const { data } = useApi<Paged<RequestRow>>(showCharts ? null : `/api/requests?${params}`, { poll: 5000 })
  const { data: summary } = useApi<Summary>('/api/dashboard/summary', { poll: 10000 })
  const s = summary?.auditor
  const reset = <T,>(fn: (v: T) => void) => (v: T) => { fn(v); setPage(1) }

  const openRow = (r: RequestRow) => {
    if (user?.role === 'AUDITOR' && ['COMPLETED', 'NOTIFIED'].includes(r.status)) nav(`/requests/${r.request_id}/final`)
    else if (user?.role === 'VALIDATOR') nav(`/queue/${r.request_id}`)
    else if (user?.role === 'SME' && ['REVIEW_READY', 'SME_REVIEW'].includes(r.status)) nav(`/approvals/${r.request_id}`)
    else nav(`/requests/${r.request_id}`)
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{mode === 'dashboard' ? `${greeting()}, ${user?.first_name}` : 'Requests'}</h1>
          <p className="page-sub">
            {mode === 'dashboard' ? 'Here is the status of all audit evidence requests across your portfolio.' : 'All audit evidence requests and their current workflow stage.'}
          </p>
        </div>
        {user?.role === 'AUDITOR' && (
          <button className="btn btn-primary btn-lg" onClick={() => nav('/requests/new')}><Plus size={18} /> Create Request</button>
        )}
      </div>

      {mode === 'dashboard' && (
        <div className="kpi-grid">
          <Kpi tone="blue" icon={<Files size={18} />} value={s?.total ?? '—'} label="Total Requests"
               pill={`${(s?.mom_delta ?? 0) >= 0 ? '+' : ''}${s?.mom_delta ?? 0} MoM`} />
          <Kpi tone="blue" icon={<Loader size={18} />} value={s?.processing ?? '—'} label="Processing" pill="live now" />
          <Kpi tone="amber" icon={<Clock size={18} />} value={s?.awaiting_review ?? '—'} label="Awaiting Review" pill="needs action" />
          <Kpi tone="green" icon={<CircleCheck size={18} />} value={s?.completed ?? '—'} label="Completed" pill={`${s?.on_time_pct ?? 100}% on time`} />
        </div>
      )}

      {showCharts ? <DashboardCharts /> : (
      <div className="card table-card">
        <div className="toolbar">
          <SearchInput value={search} onChange={reset(setSearch)} placeholder="Search by ID, vendor, document..." filled width={300} />
          <Select label="Status" value={status} onChange={reset(setStatus)} options={STATUS_OPTIONS} />
          <Select label="Query type" value={queryType} onChange={reset(setQueryType)} options={qtOptions} />
          <Select label="Period" value={period} onChange={reset(setPeriod)} options={PERIOD_OPTIONS} />
          <div className="spacer" />
          <button className="link-btn" onClick={() => setSort(sort === 'updated' ? 'created' : 'updated')}>
            <ArrowUpDown size={15} /> {sort === 'updated' ? 'Last updated' : 'Newest created'}
          </button>
        </div>
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Request ID</th><th>Query Type</th><th>Created</th><th>Status</th><th>Evidence Completeness</th><th className="right">Updated</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((r) => (
                <tr key={r.request_id} className="clickable" onClick={() => openRow(r)}>
                  <td><button className="link-btn id-link" onClick={(e) => { e.stopPropagation(); setDrawer(r.request_id) }} title="View live status">{r.request_id}</button></td>
                  <td>{r.query_type_label}</td>
                  <td className="muted">{fmtDate(r.created_at)}</td>
                  <td><StatusChip status={r.status} label={r.status_label} /></td>
                  <td style={{ width: '26%' }}><Progress pct={r.completeness_pct} status={r.status} /></td>
                  <td className="right muted"><span className="row" style={{ justifyContent: 'flex-end' }}>{fmtDate(r.updated_at)} <ChevronRight size={16} /></span></td>
                </tr>
              ))}
              {data && !data.items.length && (
                <tr><td colSpan={6}><div className="empty">No requests match these filters.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          <span>Showing {data?.items.length ?? 0} of {data?.total ?? 0} requests</span>
          <div className="pager">
            <span>Page {data?.page ?? 1} of {data?.pages ?? 1}</span>
            <button aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={15} /></button>
            <button aria-label="Next page" disabled={!data || page >= data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={15} /></button>
          </div>
        </div>
      </div>
      )}
      {drawer && <StatusDrawer requestId={drawer} onClose={() => setDrawer(null)} />}
    </>
  )
}
