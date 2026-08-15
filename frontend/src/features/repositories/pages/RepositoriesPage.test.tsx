import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { CodeRepository } from '../types'
import { RepositoriesPage } from './RepositoriesPage'

function repo(id: string): CodeRepository {
  return {
    id,
    provider: 'github',
    owner: 'acme',
    name: `repo-${id}`,
    clone_url: `https://github.com/acme/repo-${id}.git`,
    default_branch: 'main',
    has_credential: false,
    credential_kind: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RepositoriesPage />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('RepositoriesPage', () => {
  it('shows a card-grid skeleton while repositories are loading', async () => {
    server.use(
      http.get('*/api/v1/repositories', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when repositories fail to load', async () => {
    server.use(
      http.get('*/api/v1/repositories', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows an empty state with a register action when there are no repositories', async () => {
    server.use(http.get('*/api/v1/repositories', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByText(/no repositories/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /register repository/i }),
    ).toBeInTheDocument()
  })

  it('lists repositories and paginates with a load more control', async () => {
    const repositories = Array.from({ length: 12 }, (_, i) => repo(String(i)))
    server.use(
      http.get('*/api/v1/repositories', () => HttpResponse.json(repositories)),
    )
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('acme/repo-0')
    expect(screen.queryByText('acme/repo-10')).not.toBeInTheDocument()

    const loadMore = screen.getByRole('button', { name: /load more/i })
    await user.click(loadMore)

    expect(await screen.findByText('acme/repo-10')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /load more/i }),
    ).not.toBeInTheDocument()
  })
})
