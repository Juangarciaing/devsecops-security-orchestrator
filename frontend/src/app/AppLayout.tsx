import { Link, Outlet } from 'react-router'
import { useAuth } from './auth/useAuth'
import { Button } from '@/shared/ui/button'

export function AppLayout() {
  const auth = useAuth()

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-semibold tracking-tight">
            DevSecOps Security Orchestrator
          </h1>
          <nav className="flex items-center gap-4 text-sm">
            <Link to="/" className="hover:underline">
              Repositories
            </Link>
            <Link to="/findings" className="hover:underline">
              Findings
            </Link>
          </nav>
        </div>
        {auth.user ? (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{auth.user.email}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={auth.logout}
            >
              Log out
            </Button>
          </div>
        ) : null}
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  )
}
