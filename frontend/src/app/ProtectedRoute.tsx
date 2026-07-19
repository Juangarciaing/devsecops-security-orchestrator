import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { useAuth } from './auth/useAuth'

export function ProtectedRoute({ children }: { children: ReactNode }) {
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

  return <>{children}</>
}
