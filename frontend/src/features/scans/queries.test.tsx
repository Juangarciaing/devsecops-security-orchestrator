import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import {
  scanRefetchInterval,
  useRepositoryScans,
  useScan,
  useTriggerScan,
} from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const scanRun = {
  id: 's1',
  repository_id: 'r1',
  status: 'pending',
  trigger: 'manual',
  commit_sha: 'main',
  ref: 'main',
  created_at: '2026-01-01T00:00:00Z',
  started_at: null,
  completed_at: null,
}

describe('useTriggerScan', () => {
  it('posts a scan trigger for the repository and returns the created run', async () => {
    server.use(
      http.post('*/api/v1/repositories/r1/scans', () =>
        HttpResponse.json(scanRun, { status: 202 }),
      ),
    )
    const { result } = renderHook(() => useTriggerScan(), { wrapper })

    result.current.mutate({ repositoryId: 'r1' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.run).toEqual(scanRun)
    expect(result.current.data?.status).toBe(202)
  })

  it('surfaces the existing-idempotent 200 response', async () => {
    server.use(
      http.post('*/api/v1/repositories/r1/scans', () =>
        HttpResponse.json(scanRun, { status: 200 }),
      ),
    )
    const { result } = renderHook(() => useTriggerScan(), { wrapper })

    result.current.mutate({ repositoryId: 'r1' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.status).toBe(200)
  })

  it('surfaces a 404 error for an inactive or missing repository', async () => {
    server.use(
      http.post(
        '*/api/v1/repositories/r1/scans',
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
    const { result } = renderHook(() => useTriggerScan(), { wrapper })

    result.current.mutate({ repositoryId: 'r1' })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useScan', () => {
  it('fetches the scan detail', async () => {
    server.use(
      http.get('*/api/v1/scans/s1', () =>
        HttpResponse.json({
          ...scanRun,
          task_status: 'pending',
          findings_count: 0,
        }),
      ),
    )
    const { result } = renderHook(() => useScan('s1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.findings_count).toBe(0)
  })
})

// The polling cadence itself (2500ms while pending/running, stop otherwise)
// is exercised here as a pure function rather than via real/fake timers on
// the full hook — this is the exact predicate passed as `refetchInterval`
// below, so testing it directly covers the behavior deterministically and
// fast, matching the design doc's `refetchInterval` snippet.
describe('scanRefetchInterval', () => {
  it.each([
    ['pending', 2500],
    ['running', 2500],
    ['completed', false],
    ['failed', false],
    ['cancelled', false],
    [undefined, false],
  ] as const)('status %s -> %s', (status, expected) => {
    const data =
      status === undefined
        ? undefined
        : {
            ...scanRun,
            status,
            task_status: 'completed' as const,
            findings_count: 0,
          }
    expect(scanRefetchInterval(data)).toBe(expected)
  })
})

describe('useRepositoryScans', () => {
  it('fetches the scan list and filters to the given repository', async () => {
    server.use(
      http.get('*/api/v1/scans', () =>
        HttpResponse.json([
          scanRun,
          { ...scanRun, id: 's2', repository_id: 'r2' },
        ]),
      ),
    )
    const { result } = renderHook(() => useRepositoryScans('r1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([scanRun])
  })
})
