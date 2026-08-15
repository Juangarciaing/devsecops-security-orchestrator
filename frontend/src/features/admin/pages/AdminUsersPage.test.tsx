import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { AdminUsersPage } from './AdminUsersPage'

function makeUser(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    email: `user-${id}@example.com`,
    role: 'member',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminUsersPage />
    </QueryClientProvider>,
  )
}

describe('AdminUsersPage', () => {
  it('shows a table skeleton while users are loading', async () => {
    server.use(
      http.get('*/api/v1/users', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when users fail to load', async () => {
    server.use(
      http.get('*/api/v1/users', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('renders the fetched users', async () => {
    server.use(
      http.get('*/api/v1/users', () =>
        HttpResponse.json([makeUser('u1')]),
      ),
    )
    renderPage()

    expect(await screen.findByText('user-u1@example.com')).toBeInTheDocument()
  })
})
