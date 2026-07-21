import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useRepoTrends } from './queries'
import type { RepositoryTrends } from './types'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const trends: RepositoryTrends = {
  repository_id: 'r1',
  points: [
    {
      scan_run_id: 's1',
      occurred_at: '2026-01-01T00:00:00Z',
      commit_sha: 'abc123',
      introduced: { high: 2 },
    },
  ],
  current_open: { high: 2 },
}

describe('useRepoTrends', () => {
  it('fetches trend data for the given repository', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1/trends', () =>
        HttpResponse.json(trends),
      ),
    )
    const { result } = renderHook(() => useRepoTrends('r1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(trends)
  })

  it('does not fetch when no id is provided', () => {
    const fetchSpy = vi.fn()
    server.use(
      http.get('*/api/v1/repositories/:id/trends', () => {
        fetchSpy()
        return HttpResponse.json(trends)
      }),
    )
    const { result } = renderHook(() => useRepoTrends(''), { wrapper })

    expect(result.current.isPending).toBe(true)
    expect(result.current.fetchStatus).toBe('idle')
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
