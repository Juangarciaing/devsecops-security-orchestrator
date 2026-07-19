import { createBrowserRouter, type RouteObject } from 'react-router'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { FindingsPage } from '@/features/findings/pages/FindingsPage'
import { RepositoriesPage } from '@/features/repositories/pages/RepositoriesPage'
import { RepositoryDetailPage } from '@/features/repositories/pages/RepositoryDetailPage'
import { ScanDetailPage } from '@/features/scans/pages/ScanDetailPage'
import { AppLayout } from './AppLayout'
import { ProtectedRoute } from './ProtectedRoute'

function NotFound() {
  return <div className="text-muted-foreground">Not found.</div>
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
      { path: 'findings', element: <FindingsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
