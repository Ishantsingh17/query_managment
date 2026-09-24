import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { homeFor, useAuth } from './lib/auth'
import type { Role } from './lib/types'
import Shell from './components/Shell'
import { Loading } from './components/ui'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import CreateRequest from './pages/CreateRequest'
import RequestDetail from './pages/RequestDetail'
import FinalResponse from './pages/FinalResponse'
import Completed from './pages/Completed'
import ValidationQueue from './pages/ValidationQueue'
import ValidationDetail from './pages/ValidationDetail'
import ApprovalQueue from './pages/ApprovalQueue'
import ReviewPackage from './pages/ReviewPackage'
import { Help, NotFound, Reports, SettingsPage } from './pages/General'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  const loc = useLocation()
  if (!ready) return <Loading />
  if (!user) {
    const target = loc.pathname + loc.search
    return <Navigate to={loc.pathname === '/' ? '/login' : `/login?next=${encodeURIComponent(target)}`} replace />
  }
  return <>{children}</>
}

function RoleOnly({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth()
  if (user && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />
  return <>{children}</>
}

function Home() {
  const { user } = useAuth()
  return <Navigate to={user ? homeFor(user.role) : '/login'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<Home />} />
        <Route path="/dashboard" element={<RoleOnly roles={['AUDITOR', 'SME']}><Dashboard /></RoleOnly>} />
        <Route path="/requests" element={<Dashboard mode="requests" />} />
        <Route path="/requests/new" element={<RoleOnly roles={['AUDITOR']}><CreateRequest /></RoleOnly>} />
        <Route path="/requests/:id" element={<RequestDetail />} />
        <Route path="/requests/:id/final" element={<FinalResponse />} />
        <Route path="/requests/:id/package" element={<FinalResponse />} />
        <Route path="/completed" element={<Completed />} />
        <Route path="/queue" element={<RoleOnly roles={['VALIDATOR']}><ValidationQueue /></RoleOnly>} />
        <Route path="/queue/:id" element={<RoleOnly roles={['VALIDATOR']}><ValidationDetail /></RoleOnly>} />
        <Route path="/validation/requests/:id" element={<RoleOnly roles={['VALIDATOR']}><ValidationDetail /></RoleOnly>} />
        <Route path="/approvals" element={<RoleOnly roles={['SME']}><ApprovalQueue /></RoleOnly>} />
        <Route path="/approvals/:id" element={<RoleOnly roles={['SME']}><ReviewPackage /></RoleOnly>} />
        <Route path="/approvals/requests/:id" element={<RoleOnly roles={['SME']}><ReviewPackage /></RoleOnly>} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/help" element={<Help />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
