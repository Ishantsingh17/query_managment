import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setRememberedEmail, setToken, setUnauthorizedHandler } from './api'
import type { User } from './types'

export interface RedirectDecision {
  allowed: boolean
  redirect: string
  reason: string | null
  required_role?: string | null
}

interface AuthState {
  user: User | null
  ready: boolean
  sessionExpired: boolean
  login: (email: string, password: string, remember: boolean, next?: string | null) => Promise<{ user: User; redirect: RedirectDecision }>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (getToken()) setSessionExpired(true)
      setToken(null)
      setUser(null)
    })
    if (!getToken()) {
      setReady(true)
      return
    }
    api
      .get<User>('/api/auth/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true))
  }, [])

  const login = useCallback(async (email: string, password: string, remember: boolean, next?: string | null) => {
    const res = await api.post<{ token: string; user: User; redirect: RedirectDecision }>(
      '/api/auth/login', { email, password, remember, next: next ?? null })
    setToken(res.token)
    setRememberedEmail(remember ? email : null)
    setSessionExpired(false)
    setUser(res.user)
    return { user: res.user, redirect: res.redirect }
  }, [])

  const value = useMemo(() => ({ user, ready, sessionExpired, login, logout }), [user, ready, sessionExpired, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

export function homeFor(role: string): string {
  return role === 'VALIDATOR' ? '/queue' : role === 'SME' ? '/approvals' : '/dashboard'
}

export function redirectNotice(d: RedirectDecision): string | null {
  if (d.reason === 'wrong_role') return `That link is for ${d.required_role ? `the ${d.required_role}` : 'a different role'} — you have been taken to your home page.`
  if (d.reason === 'not_permitted' || d.reason === 'not_found') return 'That request is not available to your account.'
  if (d.reason === 'package_not_ready') return 'The Final Response Package is not ready yet — showing the request status instead.'
  if (d.reason === 'invalid') return 'That link is not valid — you have been taken to your home page.'
  return null
}
