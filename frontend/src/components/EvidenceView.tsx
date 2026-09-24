import { Fragment } from 'react'
import { ExternalLink } from 'lucide-react'
import { openFile } from '../lib/api'
import { useApi } from '../lib/hooks'
import { fmtDate, fmtTime } from '../lib/format'
import { EvidenceChip, EvidenceIcon, Loading, Modal, SrcTag } from './ui'

interface EvidenceDetail {
  evidence_id: string
  label: string
  icon: string
  status: string
  source_system: string | null
  source_reference: string | null
  description: string | null
  retrieval_method: string | null
  record: Record<string, unknown> | null
  records: Record<string, unknown>[]
  provenance: Record<string, unknown>
  retrieved_at: string | null
  notes: string[]
  corroboration: { source_system: string; matched: boolean; reference: string | null }[]
  uploaded_by: string | null
  justification: string | null
}

const humanize = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bPo\b/, 'PO')

/** In-app evidence preview: metadata, provenance and normalized content. */
export default function EvidenceViewModal({ evidenceId, onClose }: { evidenceId: string; onClose: () => void }) {
  const { data: ev, error } = useApi<EvidenceDetail>(`/api/evidence/${evidenceId}`)
  return (
    <Modal onClose={onClose} wide>
      {!ev && !error && <Loading />}
      {error && <div className="alert error">{error.message}</div>}
      {ev && (
        <div>
          <div className="between">
            <div className="row gap-12">
              <div className="ev-card-icon"><EvidenceIcon icon={ev.icon} /></div>
              <div>
                <div className="ev-name">{ev.label}</div>
                <div className="ev-meta">{ev.description}</div>
              </div>
            </div>
            <EvidenceChip status={ev.status} />
          </div>
          <div className="ev-ref mt-16">
            {ev.source_system && <SrcTag>{ev.source_system}</SrcTag>}
            <span>{ev.source_reference ?? '—'}</span>
            <button className="link-btn" onClick={() => openFile(`/api/evidence/${ev.evidence_id}/file`)}>Open <ExternalLink size={14} /></button>
          </div>
          <div className="eyebrow mt-20">Provenance</div>
          <dl className="kv mt-8">
            <dt>Retrieval method</dt><dd>{ev.retrieval_method === 'MANUAL_UPLOAD' ? `Manual upload${ev.uploaded_by ? ` by ${ev.uploaded_by}` : ''}` : 'Source API'}</dd>
            {ev.retrieved_at && <><dt>Retrieved</dt><dd>{fmtDate(ev.retrieved_at)} · {fmtTime(ev.retrieved_at)}</dd></>}
            {ev.provenance?.keys_used ? <><dt>Search keys</dt><dd>{Object.entries(ev.provenance.keys_used as Record<string, string>).map(([k, v]) => `${humanize(k)}: ${v}`).join(' · ')}</dd></> : null}
            {ev.corroboration?.length ? <><dt>Corroborated by</dt><dd>{ev.corroboration.map((c) => `${c.source_system} ${c.matched ? `(${c.reference})` : '(no record)'}`).join(', ')}</dd></> : null}
            {ev.justification && <><dt>Justification</dt><dd>{ev.justification}</dd></>}
            {ev.notes?.map((n, i) => <Fragment key={i}><dt>Note</dt><dd>{n}</dd></Fragment>)}
          </dl>
          {ev.record && (
            <>
              <div className="eyebrow mt-20">{ev.records.length > 1 ? `Normalized content · ${ev.records.length} records (first shown)` : 'Normalized content'}</div>
              <dl className="kv mt-8">
                {Object.entries(ev.record).map(([k, v]) => <Fragment key={k}><dt>{humanize(k)}</dt><dd>{String(v ?? '—')}</dd></Fragment>)}
              </dl>
            </>
          )}
          <div className="row mt-20" style={{ justifyContent: 'flex-end' }}>
            <button className="btn btn-outline" onClick={onClose}>Close</button>
          </div>
        </div>
      )}
    </Modal>
  )
}
