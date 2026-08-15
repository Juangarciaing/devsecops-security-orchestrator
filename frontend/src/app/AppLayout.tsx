import { Outlet } from 'react-router'
import { useAuth } from './auth/useAuth'
import { AppSidebar } from './nav/AppSidebar'
import { UserMenu } from './nav/UserMenu'

export function AppLayout() {
  const auth = useAuth()

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar role={auth.role} />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-6 py-4">
          <h1 className="text-heading">DevSecOps Security Orchestrator</h1>
          {auth.user ? (
            <UserMenu user={auth.user} onLogout={auth.logout} />
          ) : null}
        </header>
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
