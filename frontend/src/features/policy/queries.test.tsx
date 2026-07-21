import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useRepoPolicyCheck } from './queries'
import type { RepositoryPolicy } from './types'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const policy: RepositoryPolicy = {
  repository_id: 'r1',
  verdict: 'fail',
  blocking_severities: ['critical', 'high'],
  violating_counts: { critical: 2 },
}

describe('useRepoPolicyCheck', () => {
  it('fetches the policy check for the given repository', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json(policy),
      ),
    )
    const { result } = renderHook(() => useRepoPolicyCheck('r1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(policy)
  })

  it('does not fetch when no id is provided', () => {
    const fetchSpy = vi.fn()
    server.use(
      http.get('*/api/v1/repositories/:id/policy-check', () => {
        fetchSpy()
        return HttpResponse.json(policy)
      }),
    )
    const { result } = renderHook(() => useRepoPolicyCheck(''), { wrapper })

    expect(result.current.isPending).toBe(true)
    expect(result.current.fetchStatus).toBe('idle')
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
