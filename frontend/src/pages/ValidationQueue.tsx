import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../lib/hooks'
import { fmtShort } from '../lib/format'
import type { Paged, RequestRow, Summary } from '../lib/types'
import { Progress, SearchInput, Select, StatusChip } from '../components/ui'
import { useQueryTypeOptions } from './Dashboard'

export default function ValidationQueue() {
  const nav = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [queryType, setQueryType] = useState('')
  const [missing, setMissing] = useState('any')
  const [period, setPeriod] = useState('all')
  const [mine, setMine] = useState(false)
  const qtOptions = useQueryTypeOptions('Query type')

  const params = new URLSearchParams({ view: 'queue', page_size: '100', missing, period, sort: 'created' })
  const statusFilter = mine ? 'VALIDATION_PENDING,REWORK_REQUIRED' : status
  if (statusFilter) params.set('status', statusFilter)
  if (queryType) params.set('query_type', queryType)
  if (search.trim()) params.set('search', search.trim())
  const { data } = useApi<Paged<RequestRow>>(`/api/requests?${params}`, { poll: 5000 })
  const { data: summary } = useApi<Summary>('/api/dashboard/summary', { poll: 10000 })
  const attention = summary?.badges.needs_attention ?? 0
  // Oldest first (sort=created desc from API -> reverse) so the most overdue item is on top.
  const rows = [...(data?.items ?? [])].reverse()
  const firstActionable = rows.find((r) => ['VALIDATION_PENDING', 'REWORK_REQUIRED'].includes(r.status))?.request_id

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Evidence Review Queue</h1>
          <p className="page-sub">Resolve missing or unclear evidence so requests can move to SME approval.</p>
        </div>
        {attention > 0 && <span className="attention">{attention} request{attention === 1 ? '' : 's'} need attention</span>}
      </div>
      <div className="toolbar" style={{ marginBottom: 16 }}>
        <SearchInput value={search} onChange={setSearch} placeholder="Search request ID, query, vendor..." />
        <Select label="Status" value={status} onChange={setStatus} options={[
          { value: '', label: 'Status: All' }, { value: 'VALIDATION_PENDING', label: 'Validation Pending' },
          { value: 'REWORK_REQUIRED', label: 'Rework Required' }, { value: 'REVIEW_READY', label: 'Review Ready' },
          { value: 'PROCESSING', label: 'Processing' },
        ]} />
        <Select label="Query type" value={queryType} onChange={setQueryType} options={qtOptions} />
        <Select label="Missing evidence" value={missing} onChange={setMissing} options={[
          { value: 'any', label: 'Missing evidence' }, { value: 'missing', label: 'Has missing evidence' }, { value: 'complete', label: 'No missing evidence' },
        ]} />
        <Select label="Date range" value={period} onChange={setPeriod} options={[
          { value: 'all', label: 'Date range' }, { value: 'this_month', label: 'This month' }, { value: 'last_30', label: 'Last 30 days' },
        ]} />
        <div className="spacer" />
        <button className={`btn btn-lg ${mine ? 'btn-dark' : 'btn-outline'}`} onClick={() => setMine(!mine)} aria-pressed={mine}>
          My assignments only
        </button>
      </div>
      <div className="card table-card">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr><th>Request ID</th><th>Query Type</th><th>Completeness</th><th>Missing Evidence</th><th>Created</th><th>Status</th><th className="right">Action</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.request_id} className={`clickable${r.request_id === firstActionable ? ' highlight' : ''}`} onClick={() => nav(`/queue/${r.request_id}`)}>
                  <td className="id-link">{r.request_id}</td>
                  <td>{r.query_type_label}</td>
                  <td style={{ width: '17%' }}><Progress pct={r.completeness_pct} status="PROCESSING" /></td>
                  <td>{r.missing_evidence.length ? <span className="text-red">{r.missing_evidence.join(', ')}</span> : <span className="muted">—</span>}</td>
                  <td className="muted">{fmtShort(r.created_at)}</td>
                  <td><StatusChip status={r.status} label={r.status_label} /></td>
                  <td className="right">
                    <button className={`btn ${r.request_id === firstActionable ? 'btn-primary' : 'btn-outline'}`}
                            onClick={(e) => { e.stopPropagation(); nav(`/queue/${r.request_id}`) }}>Review</button>
                  </td>
                </tr>
              ))}
              {data && !rows.length && <tr><td colSpan={7}><div className="empty">The queue is clear — nothing needs validation right now.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
