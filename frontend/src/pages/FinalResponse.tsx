import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Check, CircleCheck, Download, FileCheck2 } from 'lucide-react'
import { download, openFile } from '../lib/api'
import { useApi } from '../lib/hooks'
import { fmtDate, fmtTime } from '../lib/format'
import type { FinalPackage, RequestDetail } from '../lib/types'
import { ErrorState, EvidenceIcon, Loading } from '../components/ui'
import EvidenceViewModal from '../components/EvidenceView'

export default function FinalResponse() {
  const { id = '' } = useParams()
  const [viewing, setViewing] = useState<string | null>(null)
  const { data: pkg, error } = useApi<{ final_package: FinalPackage | null; message?: string }>(`/api/requests/${id}/package`)
  const { data: d } = useApi<RequestDetail>(`/api/requests/${id}`)

  if (error) return <ErrorState message={error.message} />
  if (!pkg || !d) return <Loading />
  const fp = pkg.final_package
  if (!fp) return <ErrorState message={pkg.message ?? 'The Final Response Package is not available yet.'} />

  const approval = fp.response_metadata.approval
  const initials = approval.approver_name?.split(' ').map((p) => p[0]).slice(0, 2).join('') ?? 'SME'
  const bundle = () => download(`/api/requests/${id}/package/download`)

  return (
    <div className="final-wrap">
      <div className="final-head">
        <div className="final-check"><Check size={26} strokeWidth={3} /></div>
        <div style={{ flex: 1 }}>
          <h2>Final Response Package — Approved</h2>
          <div className="sub">{fp.request_id} · {fp.response_metadata.query_type_label} · Approved {fmtDate(approval.acted_at)} · {fmtTime(approval.acted_at)}</div>
        </div>
        <button className="btn btn-outline btn-lg" style={{ border: 0 }} onClick={bundle}><Download size={17} /> Download All</button>
      </div>
      <div className="final-body">
        <div className="final-approver">
          <div className="avatar">{initials}</div>
          <div style={{ flex: 1, fontSize: 13.5 }}>
            <strong>Approved by {approval.approver_name}</strong>
            <span className="muted"> · {approval.approver_title?.split(' · ')[0]}{approval.comment ? ` · “${approval.comment}”` : ''}</span>
          </div>
          <span className="chip green">Approved</span>
        </div>
        <div style={{ padding: '18px 28px 24px' }}>
          <div className="between" style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: 14 }}>Package contents · {fp.approved_evidence.length} approved evidence items</strong>
            <span className="muted" style={{ fontSize: 12 }}>Distinguished from the Evidence Review Package — this is the governed final record.</span>
          </div>
          <div className="stack gap-12">
            {fp.approved_evidence.map((e) => (
              <div className="final-item" key={e.evidence_id}>
                <div className="ev-card-icon"><EvidenceIcon icon={e.icon} /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ev-name">{e.label}</div>
                  <div className="ev-meta">{[e.source_system, e.source_reference, e.description].filter(Boolean).join(' · ')}</div>
                </div>
                <span className="text-green row gap-4"><CircleCheck size={16} /> Approved</span>
                <button className="btn btn-outline" onClick={() => setViewing(e.evidence_id!)}>View</button>
                <button className="btn btn-soft" onClick={() => openFile(`/api/evidence/${e.evidence_id}/file`)}>Open</button>
              </div>
            ))}
            <div className="sealed">
              <FileCheck2 size={18} />
              <span style={{ flex: 1 }}>Package sealed · checksum verified · retention-ready export (PDF + evidence bundle)</span>
              <button className="btn btn-success" onClick={bundle}>Export Bundle</button>
            </div>
            <div className="muted" style={{ fontSize: 11.5 }}>SHA-256 {fp.checksum}</div>
          </div>
        </div>
      </div>
      {viewing && <EvidenceViewModal evidenceId={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}
