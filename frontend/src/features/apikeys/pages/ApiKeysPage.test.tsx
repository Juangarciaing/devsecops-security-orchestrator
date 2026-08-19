import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { ApiKeysPage } from './ApiKeysPage'

function makeApiKey(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    user_id: 'u1',
    key_prefix: 'sk_live_abcd',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
    revoked_at: null,
    ...overrides,
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeysPage />
    </QueryClientProvider>,
  )
}

describe('ApiKeysPage', () => {
  it('shows a table skeleton while API keys are loading', async () => {
    server.use(
      http.get('*/api/v1/auth/api-keys', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when API keys fail to load', async () => {
    server.use(
      http.get(
        '*/api/v1/auth/api-keys',
        () => new HttpResponse(null, { status: 500 }),
      ),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('renders the fetched API keys', async () => {
    server.use(
      http.get('*/api/v1/auth/api-keys', () =>
        HttpResponse.json([makeApiKey('k1')]),
      ),
    )
    renderPage()

    expect(await screen.findByText('sk_live_abcd…')).toBeInTheDocument()
  })

  it('derives the stat strip from API keys', async () => {
    server.use(
      http.get('*/api/v1/auth/api-keys', () =>
        HttpResponse.json([
          makeApiKey('k1', { is_active: true }),
          makeApiKey('k2', { is_active: true }),
          makeApiKey('k3', { is_active: false }),
        ]),
      ),
    )
    renderPage()

    expect(await screen.findByText('Total keys')).toBeInTheDocument()
    const totalTile = screen.getByText('Total keys').closest('[data-slot="stat-tile"]')
    expect(totalTile).toHaveTextContent('3')
    const activeTile = screen
      .getByText('Active keys')
      .closest('[data-slot="stat-tile"]')
    expect(activeTile).toHaveTextContent('2')
    const revokedTile = screen
      .getByText('Revoked keys')
      .closest('[data-slot="stat-tile"]')
    expect(revokedTile).toHaveTextContent('1')
  })
})
