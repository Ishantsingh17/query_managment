import { useMemo, useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Building2, CircleAlert, Eye, EyeOff, Info, Lock, Mail, ShieldCheck, Shield } from 'lucide-react'
import { api, ApiError, getRememberedEmail } from '../lib/api'
import { homeFor, redirectNotice, useAuth } from '../lib/auth'
import { useToast } from '../components/ui'

export default function Login() {
  const { user, login, sessionExpired } = useAuth()
  const nav = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const next = params.get('next')
  const linkedRequest = next?.match(/AUD-\d{4}-\d+/)?.[0]
  const remembered = useMemo(getRememberedEmail, [])
  const [email, setEmail] = useState(remembered)
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [remember, setRemember] = useState(!!remembered)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(sessionExpired ? 'Session expired. Please sign in again to continue.' : null)
  const [info, setInfo] = useState<string | null>(null)

  // Email links (/login?next=...) always show the sign-in form; the backend validates `next` after sign-in.
  if (user && !next) return <Navigate to={homeFor(user.role)} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setInfo(null)
    if (!email.trim() || !password) {
      setError('Enter your corporate email and password.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { redirect } = await login(email.trim(), password, remember, next)
      const note = redirect.reason === 'package_not_ready' ? redirectNotice(redirect) : null
      if (note) toast(note)
      nav(redirect.redirect, { replace: true })
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  const sso = async () => {
    setInfo(null)
    try {
      await api.post('/api/auth/sso')
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  return (
    <div className="login">
      <section className="login-left">
        <form className="login-form" onSubmit={submit} noValidate>
          <div className="login-brand">
            <div className="brand-logo"><ShieldCheck size={21} strokeWidth={2.2} /></div>
            <div>
              <div className="brand-name">Audit Evidence Platform</div>
              <div className="brand-sub">Enterprise Assurance</div>
            </div>
          </div>
          <h1>Sign in to continue</h1>
          <p className="login-sub">
            {linkedRequest ? `Sign in to open request ${linkedRequest}.` : 'Access audit requests, evidence reviews and approvals.'}
          </p>

          <div className="field">
            <label className="label" htmlFor="email">Corporate email</label>
            <div className="input-group">
              <Mail size={17} />
              <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
                     placeholder="name@company.com" autoFocus={!remembered} />
            </div>
          </div>
          <div className="field">
            <label className="label" htmlFor="password">Password</label>
            <div className="input-group">
              <Lock size={17} />
              <input id="password" type={show ? 'text' : 'password'} autoComplete="current-password" value={password} autoFocus={!!remembered}
                     onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" />
              <button type="button" className="link-btn" style={{ color: 'var(--ink-500)' }} onClick={() => setShow(!show)}
                      aria-label={show ? 'Hide password' : 'Show password'}>
                {show ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </div>
          {error && <div className="alert error" role="alert" style={{ marginBottom: 16 }}><CircleAlert size={17} /> {error}</div>}
          {info && <div className="alert info" style={{ marginBottom: 16 }}><Info size={17} /> {info}</div>}
          <div className="between" style={{ marginBottom: 18 }}>
            <label className="checkbox">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Remember me on this device
            </label>
            <button type="button" className="link-btn" onClick={() => { setError(null); setInfo('Password resets are handled by IT support. Contact your service desk to reset your corporate password.') }}>
              Forgot password?
            </button>
          </div>
          <button className="btn btn-primary btn-block btn-lg" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in securely'}
          </button>
          <div className="or">OR</div>
          <button type="button" className="btn btn-outline btn-block btn-lg" onClick={sso}>
            <Building2 size={17} /> Continue with Enterprise SSO
          </button>
          <div className="login-foot">
            <div className="row gap-16">
              <span className="row gap-4"><Lock size={12} /> SOC 2 Type II</span>
              <span className="row gap-4"><Shield size={12} /> ISO 27001</span>
            </div>
            <span>Need help? Contact IT support</span>
          </div>
        </form>
      </section>

      <section className="login-right" aria-hidden="true">
        <div className="hero">
          <span className="hero-pill"><span className="dot green" /> Trusted by internal audit &amp; assurance teams</span>
          <h2>Evidence retrieval, validation and approval — in one governed flow.</h2>
          <p>Submit natural-language audit requests, track completeness across GROSS, ARIBA, GESS and IPAMS, and export approved response packages.</p>
          <div className="hero-card">
            <div className="hero-card-head">
              <span>REQUEST AUD-2026-1042 · PAYMENT TESTING</span>
              <span className="chip green" style={{ height: 22, fontSize: 11.5 }}>Approved</span>
            </div>
            <div className="hero-bars"><span /><span /><span /><span /></div>
            <div className="hero-tiles">
              <div>Invoice<small>GROSS</small></div>
              <div>PO<small>ARIBA</small></div>
              <div>GRN/SES<small>GESS</small></div>
              <div>Approval<small>IPAMS</small></div>
            </div>
          </div>
          <div className="hero-feats">
            <span>Full audit trail on every action</span>
            <span>Role-based access control</span>
            <span>Retention-ready exports</span>
          </div>
        </div>
      </section>
    </div>
  )
}
