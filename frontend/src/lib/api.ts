const TOKEN_KEY = 'aep.token'

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const REMEMBER_EMAIL_KEY = 'aep.remember-email'

// The session lives only in this browser tab (sessionStorage), so opening the app or an email link in a
// new tab/window always starts at the sign-in page. "Remember me" only remembers the email address.
try { localStorage.removeItem(TOKEN_KEY) } catch { /* clear sessions persisted by earlier versions */ }

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* storage unavailable */
  }
}

export function getRememberedEmail(): string {
  try {
    return localStorage.getItem(REMEMBER_EMAIL_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setRememberedEmail(email: string | null) {
  try {
    if (email) localStorage.setItem(REMEMBER_EMAIL_KEY, email)
    else localStorage.removeItem(REMEMBER_EMAIL_KEY)
  } catch {
    /* storage unavailable */
  }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network', 'We could not reach the server. Check your connection and try again.')
  }
  if (res.status === 401 && !path.startsWith('/api/auth/login')) {
    onUnauthorized?.()
  }
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const err = data?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? 'Something went wrong. Please try again.')
  }
  return data as T
}

export const api = {
  get: <T,>(p: string) => request<T>('GET', p),
  post: <T,>(p: string, body?: unknown) => request<T>('POST', p, body ?? {}),
  form: <T,>(p: string, fd: FormData) => request<T>('POST', p, fd, true),
}

/** Authenticated URL for opening files/downloads in a new tab. */
export function fileUrl(path: string): string {
  const token = getToken()
  const sep = path.includes('?') ? '&' : '?'
  return token ? `${path}${sep}token=${encodeURIComponent(token)}` : path
}

export function openFile(path: string) {
  window.open(fileUrl(path), '_blank', 'noopener')
}

export function download(path: string) {
  const a = document.createElement('a')
  a.href = fileUrl(path)
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** Multipart upload with progress callback (XHR, since fetch has no upload progress). */
export function uploadWithProgress<T>(path: string, fd: FormData, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100))
    xhr.onload = () => {
      const data = xhr.responseText ? JSON.parse(xhr.responseText) : null
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T)
      else {
        if (xhr.status === 401) onUnauthorized?.()
        reject(new ApiError(xhr.status, data?.error?.code ?? 'error', data?.error?.message ?? 'Upload failed.'))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Upload failed — check your connection and retry.'))
    xhr.send(fd)
  })
}
