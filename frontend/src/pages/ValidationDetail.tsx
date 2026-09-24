import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight, ChevronRight, CircleAlert, CircleCheck, CloudUpload, ExternalLink, FileText, FileUp, Loader2, RotateCcw, Upload, X,
} from 'lucide-react'
import { api, ApiError, openFile, uploadWithProgress } from '../lib/api'
import { useApi } from '../lib/hooks'
import { ACTIVE_STATES, fmtShort } from '../lib/format'
import type { Evidence, RequestDetail } from '../lib/types'
import { ErrorState, EvidenceChip, EvidenceIcon, Loading, Modal, SrcTag, StatusChip, useToast } from '../components/ui'
import EvidenceViewModal from '../components/EvidenceView'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.csv,.xlsx,.xls'

export default function ValidationDetail() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const { data: d, error, refresh } = useApi<RequestDetail>(`/api/requests/${id}`, { poll: 4000 })
  const [target, setTarget] = useState<string>('')
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [verified, setVerified] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [modal, setModal] = useState<'accept' | 'continue' | 'retry' | null>(null)
  const [viewing, setViewing] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const missing = d?.evidence.filter((e) => e.status === 'MISSING') ?? []
  useEffect(() => {
    if (!target && d?.evidence.length) setTarget((missing[0] ?? d.evidence[0]).evidence_type)
  }, [d, target, missing])

  if (error) return <ErrorState message={error.message} onRetry={refresh} />
  if (!d) return <Loading />

  const canAct = d.actions.includes('continue')
  const busy = ACTIVE_STATES.has(d.status)
  const targetEv = d.evidence.find((e) => e.evidence_type === target)

  const pick = (f: File | undefined | null) => {
    if (!f) return
    setUploadError(null)
    setVerified(null)
    if (f.size > 25 * 1024 * 1024) {
      setUploadError('File is larger than 25 MB.')
      return
    }
    setFile(f)
    setProgress(null)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    pick(e.dataTransfer.files?.[0])
  }

  const confirmUpload = async () => {
    if (!file || !target) return
    setUploadError(null)
    setProgress(0)
    const fd = new FormData()
    fd.append('evidence_type', target)
    fd.append('file', file)
    try {
      await uploadWithProgress(`/api/requests/${id}/evidence-upload`, fd, setProgress)
      setVerified(`${targetEv?.label ?? 'Evidence'} verified · checksum passed`)
      setFile(null)
      setProgress(null)
      toast(`${file.name} uploaded and staged.`, 'success')
      refresh()
    } catch (e) {
      setUploadError((e as ApiError).message)
      setProgress(null)
    }
  }

  const focusUpload = (evidenceType?: string) => {
    if (evidenceType) setTarget(evidenceType)
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    fileInput.current?.click()
  }

  return (
    <>
      <div className="crumbs">
        <Link to="/queue">Review Queue</Link>
        <ChevronRight size={14} />
        <strong>{d.request_id} · Validation</strong>
      </div>

      {d.approval_status === 'REJECTED' && d.decisions[0]?.action === 'REJECT' && canAct && (
        <div className="banner red">
          <CircleAlert size={18} />
          <span>Rejected by {d.decisions[0].approver_name}: “{d.decisions[0].comment}” — rework the evidence, then continue to resubmit.</span>
        </div>
      )}
      {d.status === 'REVIEW_READY' || d.status === 'SME_REVIEW' ? (
        <div className="banner green"><CircleCheck size={18} /> Evidence Review Package submitted — awaiting SME decision.</div>
      ) : null}

      <div className="grid-main-side wide-side">
        <div className="stack gap-16">
          <div className="card card-pad">
            <div className="between">
              <div className="row gap-12">
                <h2 style={{ fontSize: 20 }}>{d.request_id}</h2>
                <StatusChip status={d.status} label={d.status_label} />
              </div>
              <span className="muted">{d.query_type_label} · Due {fmtShort(d.due_at)}</span>
            </div>
            <div className="quote-box mt-16">“{d.original_query}”</div>
            {busy && <div className="alert info mt-16"><Loader2 size={16} className="spin" /> Retrieval in progress — this page updates automatically.</div>}
            <div className="ev-grid mt-16">
              {d.evidence.map((e) => (
                <EvidenceCard key={e.evidence_type} e={e} onView={setViewing} onUpload={canAct ? () => focusUpload(e.evidence_type) : undefined} />
              ))}
            </div>
          </div>

          <div className="card card-pad between action-bar" style={{ padding: '16px 20px' }}>
            <div className="row gap-12">
              <button className="btn btn-outline btn-lg" disabled={!canAct || !missing.length} onClick={() => setModal('retry')}>
                <RotateCcw size={16} /> Retry / Rework
              </button>
              <button className="btn btn-outline btn-lg" disabled={!canAct} onClick={() => focusUpload(missing[0]?.evidence_type ?? target)}>
                <Upload size={16} /> Manual Upload
              </button>
              <button className="btn btn-outline btn-lg" disabled={!canAct} onClick={() => setModal('accept')}>Accept Not Required</button>
            </div>
            <button className="btn btn-primary btn-lg" disabled={!canAct} onClick={() => setModal('continue')}
                    title={missing.length ? 'Resolve missing evidence first' : undefined}>
              Continue <ArrowRight size={16} />
            </button>
          </div>
        </div>

        <div className="card card-pad" ref={panelRef}>
          <div className="row gap-8" style={{ fontWeight: 700, fontSize: 14.5, marginBottom: 14 }}>
            <CloudUpload size={19} color="#1d56db" /> Manual upload
          </div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label className="label" htmlFor="ev-target" style={{ fontSize: 12 }}>Evidence item</label>
            <div className="select" style={{ width: '100%' }}>
              <select id="ev-target" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!canAct} style={{ width: '100%' }}>
                {d.evidence.map((e) => <option key={e.evidence_type} value={e.evidence_type}>{e.label}{e.status === 'MISSING' ? ' — missing' : ''}</option>)}
              </select>
            </div>
          </div>
          <div className={`dropzone${drag ? ' drag' : ''}`} onClick={() => canAct && fileInput.current?.click()}
               onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={canAct ? onDrop : undefined}
               role="button" tabIndex={0} aria-disabled={!canAct}>
            <FileUp size={24} color="#1d56db" />
            <div className="t">Drop {targetEv?.short_label?.toLowerCase().includes('approval') || targetEv?.label.includes('Approval') ? 'approval ' : ''}PDF here</div>
            <div className="s">or browse files · PDF, PNG · max 25 MB</div>
            <input ref={fileInput} type="file" accept={ACCEPT} hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          </div>
          {file && (
            <div className="file-row mt-12">
              <div className="row gap-8">
                <FileText size={18} color="#1d56db" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {(file.size / 1024 / 1024).toFixed(1)} MB · {progress === null ? 'ready to upload' : `uploading... ${progress}%`}
                  </div>
                </div>
                <button className="link-btn" style={{ color: 'var(--ink-500)' }} onClick={() => setFile(null)} aria-label="Remove file"><X size={17} /></button>
              </div>
              {progress !== null && <div className="bar"><div style={{ width: `${progress}%` }} /></div>}
            </div>
          )}
          {verified && <div className="alert success mt-12" style={{ alignItems: 'flex-start' }}><CircleCheck size={17} style={{ flex: 'none' }} /> {verified}</div>}
          {uploadError && <div className="alert error mt-12"><CircleAlert size={16} /> {uploadError}</div>}
          <button className="btn btn-dark btn-block btn-lg mt-16" disabled={!file || !canAct || progress !== null} onClick={confirmUpload}>
            Confirm upload
          </button>
        </div>
      </div>

      {modal === 'retry' && (
        <ConfirmRetry evidence={missing} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); toast('Retry started — re-running retrieval.', 'success') }} requestId={id} />
      )}
      {modal === 'accept' && (
        <AcceptModal evidence={d.evidence.filter((e) => e.status !== 'NOT_REQUIRED')} initial={missing[0]?.evidence_type ?? target} requestId={id}
                     onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); toast('Item accepted as not required.', 'success') }} />
      )}
      {modal === 'continue' && (
        <ContinueModal requestId={id} missingCount={missing.length} onClose={() => setModal(null)}
                       onDone={() => { setModal(null); toast(`${id} submitted to SME for approval.`, 'success'); nav('/queue') }}
                       onIncomplete={() => { setModal(null); refresh() }} />
      )}
      {viewing && <EvidenceViewModal evidenceId={viewing} onClose={() => setViewing(null)} />}
    </>
  )
}

function EvidenceCard({ e, onView, onUpload }: { e: Evidence; onView: (id: string) => void; onUpload?: () => void }) {
  const missing = e.status === 'MISSING'
  return (
    <div className={`ev-card${missing ? ' missing' : ''}`}>
      <div className="ev-card-head">
        <div className="ev-card-icon">{missing ? <CircleAlert size={18} /> : <EvidenceIcon icon={e.icon} />}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="ev-name">{e.label}</div>
          <div className="ev-meta" style={missing ? { color: 'var(--amber-700)' } : undefined}>
            {missing ? e.reason : e.status === 'NOT_REQUIRED' ? 'Accepted as not required' : e.status === 'PENDING' ? 'Retrieving from source…' : e.description}
          </div>
        </div>
        <EvidenceChip status={e.status} />
      </div>
      {missing ? (
        <div className="ev-missing-msg">
          No record was returned from {e.source_system ?? 'the source'} for this item. Upload a signed copy or mark as not required with justification.
          {onUpload && <div className="mt-8"><button className="link-btn" onClick={onUpload}><Upload size={13} /> Upload now</button></div>}
        </div>
      ) : e.status === 'NOT_REQUIRED' ? (
        <div className="ev-missing-msg" style={{ borderColor: 'var(--line)' }}>{e.justification}</div>
      ) : e.evidence_id ? (
        <div className="ev-ref">
          {e.source_system && <SrcTag>{e.source_system}</SrcTag>}
          <button className="ref-btn" title="View evidence details" onClick={() => onView(e.evidence_id!)}>{e.source_reference}</button>
          <button className="link-btn" onClick={() => openFile(`/api/evidence/${e.evidence_id}/file`)}>Open <ExternalLink size={14} /></button>
        </div>
      ) : null}
    </div>
  )
}

function ConfirmRetry({ evidence, requestId, onClose, onDone }: { evidence: Evidence[]; requestId: string; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const go = async () => {
    setBusy(true)
    try {
      await api.post(`/api/requests/${requestId}/retry`, { evidence_types: evidence.map((e) => e.evidence_type) })
      onDone()
    } catch (e) {
      setErr((e as ApiError).message)
      setBusy(false)
    }
  }
  return (
    <Modal onClose={onClose}>
      <div className="modal-icon blue"><RotateCcw size={22} /></div>
      <h3>Retry retrieval?</h3>
      <p className="modal-sub">Re-run source retrieval for {evidence.map((e) => e.label).join(', ')}. Available evidence is kept.</p>
      {err && <div className="alert error mt-12">{err}</div>}
      <div className="modal-actions">
        <button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={go} disabled={busy}>{busy ? 'Starting…' : 'Retry / Rework'}</button>
      </div>
    </Modal>
  )
}

function AcceptModal({ evidence, initial, requestId, onClose, onDone }: {
  evidence: Evidence[]; initial: string; requestId: string; onClose: () => void; onDone: () => void
}) {
  const [type, setType] = useState(initial)
  const [why, setWhy] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const go = async () => {
    if (why.trim().length < 5) {
      setErr('A justification is required to accept an item as not required.')
      return
    }
    setBusy(true)
    try {
      await api.post(`/api/requests/${requestId}/accept-not-required`, { evidence_type: type, justification: why.trim() })
      onDone()
    } catch (e) {
      setErr((e as ApiError).message)
      setBusy(false)
    }
  }
  return (
    <Modal onClose={onClose}>
      <div className="modal-icon amber"><CircleAlert size={22} /></div>
      <h3>Accept as not required?</h3>
      <p className="modal-sub">The item will be excluded from completeness and recorded as an exception in the review package.</p>
      <div className="field mt-16">
        <label className="label" htmlFor="acc-type">Evidence item</label>
        <div className="select" style={{ width: '100%' }}>
          <select id="acc-type" value={type} onChange={(e) => setType(e.target.value)} style={{ width: '100%' }}>
            {evidence.map((e) => <option key={e.evidence_type} value={e.evidence_type}>{e.label}</option>)}
          </select>
        </div>
      </div>
      <div className="field mt-12">
        <label className="label" htmlFor="acc-why">Justification <span style={{ color: 'var(--red-700)' }}>*</span></label>
        <textarea id="acc-why" className={`textarea${err ? ' error' : ''}`} rows={3} value={why} onChange={(e) => { setWhy(e.target.value); setErr(null) }}
                  placeholder="e.g. Payment below approval threshold per policy FIN-07" />
        {err && <div className="error-text"><CircleAlert size={13} /> {err}</div>}
      </div>
      <div className="modal-actions">
        <button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-dark" onClick={go} disabled={busy}>{busy ? 'Saving…' : 'Accept Not Required'}</button>
      </div>
    </Modal>
  )
}

function ContinueModal({ requestId, missingCount, onClose, onDone, onIncomplete }: {
  requestId: string; missingCount: number; onClose: () => void; onDone: () => void; onIncomplete: () => void
}) {
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      await api.post(`/api/requests/${requestId}/continue`, { note: note.trim() || null })
      onDone()
    } catch (e) {
      const ae = e as ApiError
      setErr(ae.message)
      setBusy(false)
      if (ae.code === 'incomplete') window.setTimeout(onIncomplete, 2500)
    }
  }
  return (
    <Modal onClose={onClose}>
      <div className="modal-icon blue"><ArrowRight size={22} /></div>
      <h3>Submit for SME approval?</h3>
      <p className="modal-sub">
        {missingCount ? `${missingCount} item${missingCount === 1 ? ' is' : 's are'} still missing — resolve or accept before continuing.`
          : 'Completeness will be re-checked and the Evidence Review Package sent to the Final Approver.'}
      </p>
      <div className="field mt-16">
        <label className="label" htmlFor="val-note">Validator note <span className="opt">(optional)</span></label>
        <textarea id="val-note" className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. All sources reconciled" />
      </div>
      {err && <div className="alert error mt-12"><CircleAlert size={16} /> {err}</div>}
      <div className="modal-actions">
        <button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={go} disabled={busy}>{busy ? 'Submitting…' : 'Continue'}</button>
      </div>
    </Modal>
  )
}
