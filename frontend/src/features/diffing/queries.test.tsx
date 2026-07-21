import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useRepoDiff } from './queries'
import type { RepositoryDiff } from './types'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const diff: RepositoryDiff = {
  repository_id: 'r1',
  latest_run: {
    scan_run_id: 's2',
    occurred_at: '2026-01-02T00:00:00Z',
    commit_sha: 'def5678',
  },
  baseline_run: {
    scan_run_id: 's1',
    occurred_at: '2026-01-01T00:00:00Z',
    commit_sha: 'abc123',
  },
  added: [],
  resolved: [],
  carried: [],
}

describe('useRepoDiff', () => {
  it('fetches diff data for the given repository', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1/diff', () => HttpResponse.json(diff)),
    )
    const { result } = renderHook(() => useRepoDiff('r1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(diff)
  })

  it('does not fetch when no id is provided', () => {
    const fetchSpy = vi.fn()
    server.use(
      http.get('*/api/v1/repositories/:id/diff', () => {
        fetchSpy()
        return HttpResponse.json(diff)
      }),
    )
    const { result } = renderHook(() => useRepoDiff(''), { wrapper })

    expect(result.current.isPending).toBe(true)
    expect(result.current.fetchStatus).toBe('idle')
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
