import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useApiKeys, useIssueApiKey } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const ownKey = {
  id: 'k1',
  user_id: 'u1',
  key_prefix: 'sk_ab12',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
}

describe('useApiKeys', () => {
  it('fetches only the caller-scoped key list the backend returns', async () => {
    server.use(http.get('*/api/v1/auth/api-keys', () => HttpResponse.json([ownKey])))
    const { result } = renderHook(() => useApiKeys(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([ownKey])
  })
})

describe('useIssueApiKey', () => {
  it('issues a key and returns the one-time raw key alongside the created record', async () => {
    server.use(
      http.post('*/api/v1/auth/api-keys', () =>
        HttpResponse.json(
          { api_key: ownKey, raw_key: 'sk_ab12cd34ef56' },
          { status: 201 },
        ),
      ),
    )
    const { result } = renderHook(() => useIssueApiKey(), { wrapper })

    result.current.mutate()

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({
      api_key: ownKey,
      raw_key: 'sk_ab12cd34ef56',
    })
  })
})
