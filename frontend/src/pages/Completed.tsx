import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, PackageCheck, RotateCcw } from 'lucide-react'
import { download } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/hooks'
import { fmtDate } from '../lib/format'
import type { Paged, RequestRow } from '../lib/types'
import { Chip, SearchInput, Select } from '../components/ui'
import { useQueryTypeOptions } from './Dashboard'

export default function Completed() {
  const nav = useNavigate()
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [approval, setApproval] = useState('all')
  const [queryType, setQueryType] = useState('')
  const [period, setPeriod] = useState('all')
  const qtOptions = useQueryTypeOptions('Query type')

  const params = new URLSearchParams({ view: 'completed', page_size: '100', approval, period })
  if (queryType) params.set('query_type', queryType)
  if (search.trim()) params.set('search', search.trim())
  const { data } = useApi<Paged<RequestRow>>(`/api/requests?${params}`, { poll: 15000 })

  const view = (r: RequestRow) => {
    if (r.final_response_ready) nav(`/requests/${r.request_id}/final`)
    else if (user?.role === 'VALIDATOR') nav(`/queue/${r.request_id}`)
    else nav(`/requests/${r.request_id}`)
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Completed Requests</h1>
          <p className="page-sub">Access approved Final Response Packages and review completed decisions.</p>
        </div>
        <button className="btn btn-outline btn-lg" onClick={() => download('/api/requests/export.csv?view=completed')}>
          <Download size={17} /> Export register
        </button>
      </div>
      <div className="toolbar" style={{ marginBottom: 16 }}>
        <SearchInput value={search} onChange={setSearch} placeholder="Search completed requests..." />
        <Select label="Approval" value={approval} onChange={setApproval} options={[
          { value: 'all', label: 'Approval: All' }, { value: 'APPROVED', label: 'Approved' }, { value: 'REJECTED', label: 'Rejected' },
        ]} />
        <Select label="Query type" value={queryType} onChange={setQueryType} options={qtOptions} />
        <Select label="Completed date" value={period} onChange={setPeriod} options={[
          { value: 'all', label: 'Completed date' }, { value: 'this_month', label: 'This month' },
          { value: 'last_30', label: 'Last 30 days' }, { value: 'last_90', label: 'Last 90 days' },
        ]} />
      </div>
      <div className="card table-card">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr><th>Request ID</th><th>Query Type</th><th>Completed</th><th>Approval</th><th>Final Response</th><th className="right">View</th></tr>
            </thead>
            <tbody>
              {data?.items.map((r) => (
                <tr key={r.request_id} className="clickable" onClick={() => view(r)}>
                  <td className="id-link">{r.request_id}</td>
                  <td>{r.query_type_label}</td>
                  <td className="muted">{fmtDate(r.decided_at)}</td>
                  <td>{r.decision === 'REJECT' ? <Chip tone="red">Rejected</Chip> : <Chip tone="green">Approved</Chip>}</td>
                  <td>
                    {r.final_response_ready
                      ? <span className="text-green row gap-8"><PackageCheck size={16} /> Final Response ready</span>
                      : <span className="muted row gap-8" style={{ fontWeight: 500 }}><RotateCcw size={15} /> Returned to rework</span>}
                  </td>
                  <td className="right"><button className="btn btn-outline" onClick={(e) => { e.stopPropagation(); view(r) }}>View</button></td>
                </tr>
              ))}
              {data && !data.items.length && <tr><td colSpan={6}><div className="empty">No completed requests yet.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
