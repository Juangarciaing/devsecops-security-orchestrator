import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import {
  useFindings,
  useScanFindings,
  useSuppressFinding,
  useUnsuppressFinding,
} from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const finding = {
  id: 'f1',
  scan_task_id: 't1',
  severity: 'high',
  status: 'open',
  rule_id: 'generic-api-key',
  title: 'Hardcoded API key',
  fingerprint: 'abc123',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  description: null,
  file_path: 'src/config.ts',
  line_number: 12,
  raw_evidence: { match: 'sk-***' },
  snippet: 'const key = "sk-***"',
  repository_id: 'r1',
  first_seen_scan_run_id: 's1',
  last_seen_scan_run_id: 's1',
}

describe('useScanFindings', () => {
  it('fetches findings scoped to a scan run', async () => {
    server.use(
      http.get('*/api/v1/scans/s1/findings', () =>
        HttpResponse.json([finding]),
      ),
    )
    const { result } = renderHook(() => useScanFindings('s1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([finding])
  })
})

describe('useFindings', () => {
  it('sends the filters and pagination as query params', async () => {
    let capturedUrl: URL | undefined
    server.use(
      http.get('*/api/v1/findings', ({ request }) => {
        capturedUrl = new URL(request.url)
        return HttpResponse.json([finding])
      }),
    )
    const { result } = renderHook(
      () =>
        useFindings({
          severity: 'high',
          status: 'open',
          repository_id: 'r1',
          scanner_type: 'secrets',
          limit: 20,
          offset: 0,
        }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([finding])
    expect(capturedUrl?.searchParams.get('severity')).toBe('high')
    expect(capturedUrl?.searchParams.get('status')).toBe('open')
    expect(capturedUrl?.searchParams.get('repository_id')).toBe('r1')
    expect(capturedUrl?.searchParams.get('scanner_type')).toBe('secrets')
    expect(capturedUrl?.searchParams.get('limit')).toBe('20')
    expect(capturedUrl?.searchParams.get('offset')).toBe('0')
  })

  it('omits undefined filters from the query params', async () => {
    let capturedUrl: URL | undefined
    server.use(
      http.get('*/api/v1/findings', ({ request }) => {
        capturedUrl = new URL(request.url)
        return HttpResponse.json([])
      }),
    )
    const { result } = renderHook(() => useFindings({ limit: 20, offset: 0 }), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl?.searchParams.has('severity')).toBe(false)
    expect(capturedUrl?.searchParams.has('status')).toBe(false)
    expect(capturedUrl?.searchParams.has('repository_id')).toBe(false)
    expect(capturedUrl?.searchParams.has('scanner_type')).toBe(false)
  })
})

describe('useSuppressFinding', () => {
  it('posts a suppress action and returns the updated finding', async () => {
    server.use(
      http.post('*/api/v1/findings/f1/suppress', () =>
        HttpResponse.json({ ...finding, status: 'suppressed' }),
      ),
    )
    const { result } = renderHook(() => useSuppressFinding(), { wrapper })

    result.current.mutate('f1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.status).toBe('suppressed')
  })
})

describe('useUnsuppressFinding', () => {
  it('posts an unsuppress action and returns the updated finding', async () => {
    server.use(
      http.post('*/api/v1/findings/f1/unsuppress', () =>
        HttpResponse.json({ ...finding, status: 'open' }),
      ),
    )
    const { result } = renderHook(() => useUnsuppressFinding(), { wrapper })

    result.current.mutate('f1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.status).toBe('open')
  })
})
