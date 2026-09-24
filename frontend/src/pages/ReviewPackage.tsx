import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Check, ChevronRight, CircleAlert, CircleCheck, ExternalLink, History, Quote, X } from 'lucide-react'
import { api, ApiError, openFile } from '../lib/api'
import { useApi } from '../lib/hooks'
import { fmtShort } from '../lib/format'
import type { RequestDetail } from '../lib/types'
import { ErrorState, EvidenceChip, EvidenceIcon, Loading, Modal, SrcTag, StatusChip, useToast } from '../components/ui'
import EvidenceViewModal from '../components/EvidenceView'

export default function ReviewPackage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const { data: d, error, refresh } = useApi<RequestDetail>(`/api/requests/${id}`, { poll: 8000 })
  const [comment, setComment] = useState('')
  const [commentError, setCommentError] = useState(false)
  const [modal, setModal] = useState<'approve' | 'reject' | null>(null)
  const [viewing, setViewing] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<{ tone: 'green' | 'red'; text: string } | null>(null)
  const opened = useRef(false)

  useEffect(() => {
    if (outcome) window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [outcome])

  useEffect(() => {
    if (d && !opened.current && d.status === 'REVIEW_READY') {
      opened.current = true
      api.post(`/api/requests/${id}/open-review`).then(refresh).catch(() => {})
    }
  }, [d, id, refresh])

  if (error) return <ErrorState message={error.message} onRetry={refresh} />
  if (!d) return <Loading />

  const canDecide = d.actions.includes('approve')
  const c = d.counts
  const shown = d.evidence.filter((e) => e.status !== 'NOT_REQUIRED')
  const exceptions = d.evidence.filter((e) => e.status === 'NOT_REQUIRED')
  const done = c ? c.available + c.manual : 0

  const startReject = () => {
    if (!comment.trim()) {
      setCommentError(true)
      return
    }
    setModal('reject')
  }

  return (
    <>
      <div className="crumbs">
        <Link to="/approvals">Approvals</Link>
        <ChevronRight size={14} />
        <strong>{d.request_id} · Evidence Review Package</strong>
      </div>

      {outcome && (
        <div className={`banner ${outcome.tone}`}>
          {outcome.tone === 'green' ? <CircleCheck size={18} /> : <CircleAlert size={18} />} {outcome.text}
          <button className="btn btn-outline btn-sm" style={{ marginLeft: 'auto' }} onClick={() => nav('/approvals')}>Back to queue</button>
        </div>
      )}
      {!outcome && d.actions.includes('finalize') && (
        <div className="banner red">
          <CircleAlert size={18} /> Approved, but the Final Response Package could not be generated.
          <button className="btn btn-danger btn-sm" style={{ marginLeft: 'auto' }} onClick={async () => {
            try { await api.post(`/api/requests/${id}/finalize`); toast('Final Response Package generated.', 'success'); refresh() }
            catch (e) { toast((e as ApiError).message, 'error') }
          }}>Regenerate package</button>
        </div>
      )}

      <div className="grid-main-side" style={{ gridTemplateColumns: 'minmax(0,1fr) 305px' }}>
        <div className="stack gap-12">
          <div className="card card-pad">
            <div className="between">
              <div className="row gap-12">
                <h2 style={{ fontSize: 20 }}>{d.request_id}</h2>
                <StatusChip status={d.status} label={d.status_label} />
              </div>
              {d.validated_by && (
                <span className="text-green row gap-4" style={{ fontSize: 13 }}>
                  <CircleCheck size={16} /> Validated by {abbrev(d.validated_by)} · {fmtShort(d.validated_at)}
                </span>
              )}
            </div>
            <div className="quote-box mt-16">“{d.original_query}”</div>
            <div className="row gap-12 mt-16" style={{ alignItems: 'stretch' }}>
              <InfoTile label="Query type" value={d.query_type_label} />
              <InfoTile label="Completeness" value={c ? `${done} of ${c.required - c.not_required} · ${c.completeness_pct}%` : '—'} />
              <InfoTile label="Validator note" value={d.validator_note || (exceptions.length ? `${exceptions.length} item(s) accepted as not required` : 'All sources reconciled')} />
            </div>
          </div>

          {shown.map((e) => (
            <div className="card ev-list-card" key={e.evidence_type}>
              <div className="ev-card-head">
                <div className="ev-card-icon"><EvidenceIcon icon={e.icon} /></div>
                <div style={{ flex: 1 }}>
                  <div className="ev-name">{e.label}</div>
                  <div className="ev-meta">{e.status === 'MANUALLY_UPLOADED' ? `${e.description?.split(' · ')[0] ?? 'Document'} · uploaded by validator` : e.description}</div>
                </div>
                <EvidenceChip status={e.status === 'MANUALLY_UPLOADED' ? 'AVAILABLE' : e.status} />
              </div>
              {e.evidence_id && (
                <div className="ev-ref mt-12">
                  {e.source_system && <SrcTag>{e.source_system}</SrcTag>}
                  <button className="ref-btn" title="View evidence details" onClick={() => setViewing(e.evidence_id!)}>{e.source_reference}</button>
                  <button className="link-btn" onClick={() => openFile(`/api/evidence/${e.evidence_id}/file`)}>Open <ExternalLink size={14} /></button>
                </div>
              )}
            </div>
          ))}
          {exceptions.map((e) => (
            <div className="card ev-list-card" key={e.evidence_type} style={{ background: '#fafbfd' }}>
              <div className="ev-card-head">
                <div className="ev-card-icon"><X size={18} /></div>
                <div style={{ flex: 1 }}>
                  <div className="ev-name">{e.label}</div>
                  <div className="ev-meta">Exception — accepted as not required: {e.justification}</div>
                </div>
                <EvidenceChip status="NOT_REQUIRED" />
              </div>
            </div>
          ))}
        </div>

        <div className="card card-pad">
          <div className="card-title">Decision</div>
          <p className="muted" style={{ margin: '6px 0 16px', lineHeight: 1.5 }}>Your approval releases the Final Response Package to the auditor.</p>
          <label className="label" htmlFor="decision-comment">Decision comment <span style={{ color: 'var(--red-700)' }}>*</span></label>
          <textarea id="decision-comment" className={`textarea mt-8${commentError ? ' error' : ''}`} rows={4} value={comment} disabled={!canDecide}
                    onChange={(e) => { setComment(e.target.value); setCommentError(false) }}
                    placeholder="Add a comment — required when rejecting, recommended when approving..." />
          {commentError && <div className="error-text mt-8"><CircleAlert size={14} /> A comment is required to reject this package.</div>}
          <button className="btn btn-success btn-block btn-lg mt-16" disabled={!canDecide} onClick={() => setModal('approve')}>
            <Check size={18} strokeWidth={2.6} /> Approve Package
          </button>
          <button className="btn btn-danger-outline btn-block btn-lg mt-12" disabled={!canDecide} onClick={startReject}>Reject Package</button>
          <div className="row gap-8 mt-16" style={{ background: 'var(--tile)', borderRadius: 8, padding: '10px 12px', color: 'var(--ink-600)', fontSize: 12.5 }}>
            <History size={15} /> Decision is logged with timestamp &amp; identity
          </div>
          {!canDecide && !outcome && d.decisions[0] && (
            <div className="hint mt-12">
              {d.decisions[0].action === 'APPROVE' ? 'Approved' : 'Rejected'} by {d.decisions[0].approver_name} on {fmtShort(d.decisions[0].acted_at)}.
            </div>
          )}
        </div>
      </div>

      {modal === 'approve' && (
        <DecisionModal kind="approve" d={d} comment={comment} onClose={() => setModal(null)}
                       onDone={() => { setModal(null); setOutcome({ tone: 'green', text: `Package approved — the Final Response Package for ${d.request_id} was released to the auditor.` }); refresh() }} />
      )}
      {modal === 'reject' && (
        <DecisionModal kind="reject" d={d} comment={comment} onClose={() => setModal(null)}
                       onDone={() => { setModal(null); setOutcome({ tone: 'red', text: `Package rejected — ${d.request_id} returned to Validation as Rework Required.` }); refresh() }} />
      )}
      {viewing && <EvidenceViewModal evidenceId={viewing} onClose={() => setViewing(null)} />}
    </>
  )
}

function abbrev(name: string) {
  const parts = name.split(' ')
  return parts.length > 1 && !name.startsWith('Automated') ? `${parts[0][0]}. ${parts.slice(1).join(' ')}` : name
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile" style={{ flex: 1, padding: '12px 14px' }}>
      <div className="muted" style={{ fontSize: 12.5 }}>{label}</div>
      <div style={{ fontWeight: 700, marginTop: 4, fontSize: 13.5 }}>{value}</div>
    </div>
  )
}

function DecisionModal({ kind, d, comment, onClose, onDone }: {
  kind: 'approve' | 'reject'; d: RequestDetail; comment: string; onClose: () => void; onDone: () => void
}) {
  const [reason, setReason] = useState(comment)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const c = d.counts
  const go = async () => {
    if (kind === 'reject' && !reason.trim()) {
      setErr('A rejection reason is required.')
      return
    }
    setBusy(true)
    try {
      await api.post(`/api/requests/${d.request_id}/${kind}`, { comment: (kind === 'reject' ? reason : comment).trim() || null })
      onDone()
    } catch (e) {
      setErr((e as ApiError).message)
      setBusy(false)
    }
  }
  if (kind === 'approve') {
    return (
      <Modal onClose={onClose}>
        <div className="modal-icon green"><Check size={24} strokeWidth={2.6} /></div>
        <h3>Approve this package?</h3>
        <p className="modal-sub">
          {d.request_id} · {d.query_type_label} · {c ? `${c.available + c.manual} of ${c.required - c.not_required}` : ''} evidence verified. Approval releases the Final Response Package.
        </p>
        {comment.trim() && <div className="quote-inline"><Quote size={15} style={{ flex: 'none', marginTop: 2 }} /> “{comment.trim()}”</div>}
        {err && <div className="alert error mt-12">{err}</div>}
        <div className="modal-actions">
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn btn-success" onClick={go} disabled={busy}><Check size={16} strokeWidth={2.6} /> {busy ? 'Approving…' : 'Approve Package'}</button>
        </div>
      </Modal>
    )
  }
  return (
    <Modal onClose={onClose}>
      <div className="modal-icon red"><X size={24} strokeWidth={2.4} /></div>
      <h3>Reject this package?</h3>
      <p className="modal-sub">{d.request_id} will return to Validation as Rework Required.</p>
      <div className="field mt-16">
        <label className="label" htmlFor="reject-reason">Rejection reason <span style={{ color: 'var(--red-700)' }}>*</span></label>
        <textarea id="reject-reason" className="textarea error" rows={3} value={reason} onChange={(e) => { setReason(e.target.value); setErr(null) }} />
      </div>
      {err && <div className="error-text mt-8"><CircleAlert size={13} /> {err}</div>}
      <div className="modal-actions">
        <button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" onClick={go} disabled={busy}>{busy ? 'Rejecting…' : 'Reject Package'}</button>
      </div>
    </Modal>
  )
}
