import { createBrowserRouter, type RouteObject } from 'react-router'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { FindingsPage } from '@/features/findings/pages/FindingsPage'
import { RepositoriesPage } from '@/features/repositories/pages/RepositoriesPage'
import { RepositoryDetailPage } from '@/features/repositories/pages/RepositoryDetailPage'
import { ScanDetailPage } from '@/features/scans/pages/ScanDetailPage'
import { TargetsPage } from '@/features/targets/pages/TargetsPage'
import { WebhookDeliveriesPage } from '@/features/webhooks/pages/WebhookDeliveriesPage'
import { AdminRoute } from './AdminRoute'
import { AppLayout } from './AppLayout'
import { PalettePreviewPage } from './PalettePreviewPage'
import { ProtectedRoute } from './ProtectedRoute'

function NotFound() {
  return <div className="text-muted-foreground">Not found.</div>
}

// Wired ahead of its feature UI — replaced by features/admin (PR6),
// features/apikeys (PR7).
function Placeholder({ text }: { text: string }) {
  return <div className="text-muted-foreground">{text}</div>
}

// Dev-only design-token preview (task 1.6) — never linked from nav, and
// `import.meta.env.DEV` is statically replaced by Vite so this route (and
// the PalettePreviewPage import) is stripped entirely from production
// builds.
const devOnlyRoutes: RouteObject[] = import.meta.env.DEV
  ? [{ path: '/dev/palette-preview', element: <PalettePreviewPage /> }]
  : []

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  ...devOnlyRoutes,
  {
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <RepositoriesPage /> },
      {
        path: 'repositories/:id',
        element: <RepositoryDetailPage />,
      },
      { path: 'scans/:id', element: <ScanDetailPage /> },
      { path: 'targets', element: <TargetsPage /> },
      { path: 'findings', element: <FindingsPage /> },
      {
        path: 'admin/users',
        element: (
          <AdminRoute>
            <Placeholder text="Admin: manage users." />
          </AdminRoute>
        ),
      },
      {
        path: 'admin/webhooks',
        element: (
          <AdminRoute>
            <WebhookDeliveriesPage />
          </AdminRoute>
        ),
      },
      {
        path: 'settings/api-keys',
        element: <Placeholder text="Manage your API keys." />,
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
