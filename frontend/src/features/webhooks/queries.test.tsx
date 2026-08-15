import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useWebhookDeliveries } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

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

describe('useWebhookDeliveries', () => {
  it('fetches the delivery list from the admin-gated endpoint', async () => {
    server.use(
      http.get('*/api/v1/webhooks/deliveries', () =>
        HttpResponse.json([makeDelivery('d1')]),
      ),
    )
    const { result } = renderHook(() => useWebhookDeliveries({ limit: 20, offset: 0 }), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([makeDelivery('d1')])
  })

  it('forwards limit/offset as query params (D8 pagination)', async () => {
    let seenLimit = ''
    let seenOffset = ''
    server.use(
      http.get('*/api/v1/webhooks/deliveries', ({ request }) => {
        const url = new URL(request.url)
        seenLimit = url.searchParams.get('limit') ?? ''
        seenOffset = url.searchParams.get('offset') ?? ''
        return HttpResponse.json([])
      }),
    )
    const { result } = renderHook(() => useWebhookDeliveries({ limit: 20, offset: 20 }), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(seenLimit).toBe('20')
    expect(seenOffset).toBe('20')
  })
})
