import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { WebhookDeliveriesPage } from './WebhookDeliveriesPage'

function makeDelivery(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    signature_valid: true,
    outcome: 'accepted',
    received_at: '2026-01-01T00:00:00Z',
    delivery_id: `gh-${id}`,
    event_type: 'push',
    source_ip: '203.0.113.7',
    repository_full_name: 'acme/widgets',
    ref: 'refs/heads/main',
    commit_sha: 'abc123',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <WebhookDeliveriesPage />
    </QueryClientProvider>,
  )
}

describe('WebhookDeliveriesPage', () => {
  it('shows a table skeleton while deliveries are loading', async () => {
    server.use(
      http.get('*/api/v1/webhooks/deliveries', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when deliveries fail to load', async () => {
    server.use(
      http.get(
        '*/api/v1/webhooks/deliveries',
        () => new HttpResponse(null, { status: 500 }),
      ),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('renders the fetched deliveries', async () => {
    server.use(
      http.get('*/api/v1/webhooks/deliveries', () =>
        HttpResponse.json([makeDelivery('d1')]),
      ),
    )
    renderPage()

    expect(await screen.findByText('acme/widgets')).toBeInTheDocument()
  })

  it('advances the offset via the Next button using real server-side pagination', async () => {
    const user = userEvent.setup()
    const seenOffsets: string[] = []
    server.use(
      http.get('*/api/v1/webhooks/deliveries', ({ request }) => {
        const url = new URL(request.url)
        const offset = url.searchParams.get('offset') ?? '0'
        seenOffsets.push(offset)
        return HttpResponse.json(
          Array.from({ length: 20 }, (_, i) =>
            makeDelivery(`p${offset}-${i}`, {
              repository_full_name: `repo-${offset}-${i}`,
            }),
          ),
        )
      }),
    )
    renderPage()

    await screen.findByText('repo-0-0')
    await user.click(screen.getByRole('button', { name: /next/i }))

    expect(await screen.findByText('repo-20-0')).toBeInTheDocument()
    await waitFor(() => expect(seenOffsets).toEqual(['0', '20']))
  })
})
