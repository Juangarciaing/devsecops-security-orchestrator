import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { RepositoryDetailPage } from './RepositoryDetailPage'

const repo = {
  id: 'r1',
  provider: 'github',
  owner: 'acme',
  name: 'widgets',
  clone_url: 'https://github.com/acme/widgets.git',
  default_branch: 'main',
  credential_ref: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderPage(id: string) {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={[`/repositories/${id}`]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Routes>
            <Route
              path="/repositories/:id"
              element={<RepositoryDetailPage />}
            />
          </Routes>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('RepositoryDetailPage', () => {
  it('shows repository info, a trigger-scan action, and an empty scan history state', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
      http.get('*/api/v1/scans', () => HttpResponse.json([])),
    )
    renderPage('r1')

    expect(await screen.findByText('acme/widgets')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /trigger scan/i }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/no scans/i)).toBeInTheDocument()
  })

  it('lists prior scans for the repository, filtered from the full scan list', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
      http.get('*/api/v1/scans', () =>
        HttpResponse.json([
          {
            id: 's1',
            repository_id: 'r1',
            status: 'completed',
            trigger: 'manual',
            commit_sha: 'main',
            ref: 'main',
            created_at: '2026-01-01T00:00:00Z',
            started_at: '2026-01-01T00:00:01Z',
            completed_at: '2026-01-01T00:00:10Z',
          },
          {
            id: 's2',
            repository_id: 'other-repo',
            status: 'completed',
            trigger: 'manual',
            commit_sha: 'main',
            ref: 'main',
            created_at: '2026-01-01T00:00:00Z',
            started_at: null,
            completed_at: null,
          },
        ]),
      ),
    )
    renderPage('r1')

    expect(await screen.findByRole('link', { name: /view/i })).toHaveAttribute(
      'href',
      '/scans/s1',
    )
  })

  it('shows a not-found message for a missing repository', async () => {
    server.use(
      http.get(
        '*/api/v1/repositories/r1',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Not Found',
              detail: 'Repository not found',
            }),
            {
              status: 404,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    renderPage('r1')

    expect(await screen.findByText(/repository not found/i)).toBeInTheDocument()
  })
})
