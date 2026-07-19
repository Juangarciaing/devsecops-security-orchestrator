import { createBrowserRouter, type RouteObject } from 'react-router'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { RepositoriesPage } from '@/features/repositories/pages/RepositoriesPage'
import { RepositoryDetailPage } from '@/features/repositories/pages/RepositoryDetailPage'
import { ScanDetailPage } from '@/features/scans/pages/ScanDetailPage'
import { AppLayout } from './AppLayout'
import { ProtectedRoute } from './ProtectedRoute'

// Placeholder leaf page for the findings route, owned by PR3. Registered now
// so route guarding covers every protected path from PR1 onward; PR3 swaps
// the element, not the path.
function ComingSoon({ label }: { label: string }) {
  return <div className="text-muted-foreground">{label} — coming soon.</div>
}

export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
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
      { path: 'findings', element: <ComingSoon label="Findings" /> },
      { path: '*', element: <ComingSoon label="Not found" /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
