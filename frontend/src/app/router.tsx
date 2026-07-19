import { createBrowserRouter, type RouteObject } from 'react-router'
import { LoginPage } from '@/features/auth/pages/LoginPage'
import { AppLayout } from './AppLayout'
import { ProtectedRoute } from './ProtectedRoute'

// Placeholder leaf pages for routes owned by PR2 (repositories/scans) and
// PR3 (findings). Registered now so route guarding covers every protected
// path from PR1 onward; PR2/PR3 swap the element, not the path.
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
      { index: true, element: <ComingSoon label="Repositories" /> },
      {
        path: 'repositories/:id',
        element: <ComingSoon label="Repository detail" />,
      },
      { path: 'scans/:id', element: <ComingSoon label="Scan detail" /> },
      { path: 'findings', element: <ComingSoon label="Findings" /> },
      { path: '*', element: <ComingSoon label="Not found" /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
