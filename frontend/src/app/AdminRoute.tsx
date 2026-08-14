import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { useAuth } from './auth/useAuth'

// Mirrors ProtectedRoute (design D10) but renders a 403 panel for non-admin
// instead of a silent redirect — UX only; require_role(ADMIN) is the gate.
export function AdminRoute({ children }: { children: ReactNode }) {
  const auth = useAuth()

  if (auth.status === 'loading') {
    return (
      <div
        role="status"
        className="flex min-h-screen items-center justify-center"
      >
        Loading…
      </div>
    )
  }

  if (auth.status === 'anon') {
    return <Navigate to="/login" replace />
  }

  if (auth.role !== 'admin') {
    return (
      <div
        role="alert"
        className="flex min-h-screen flex-col items-center justify-center gap-2 p-6 text-center"
      >
        <h1 className="text-lg font-semibold">Access denied</h1>
        <p className="text-sm text-muted-foreground">
          You need administrator access to view this page.
        </p>
      </div>
    )
  }

  return <>{children}</>
}
