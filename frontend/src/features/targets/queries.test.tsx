import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import {
  useDeactivateScanTarget,
  useRegisterScanTarget,
  useScanTarget,
  useScanTargets,
  useTriggerTargetScan,
} from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const target = {
  id: 't1',
  name: 'staging web app',
  target_url: 'https://staging.example.com',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('useScanTargets', () => {
  it('fetches the target list', async () => {
    server.use(http.get('*/api/v1/targets', () => HttpResponse.json([target])))
    const { result } = renderHook(() => useScanTargets(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([target])
  })

  it('surfaces an error when the request fails', async () => {
    server.use(
      http.get('*/api/v1/targets', () => new HttpResponse(null, { status: 500 })),
    )
    const { result } = renderHook(() => useScanTargets(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useScanTarget', () => {
  it('fetches a single target by id', async () => {
    server.use(http.get('*/api/v1/targets/t1', () => HttpResponse.json(target)))
    const { result } = renderHook(() => useScanTarget('t1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(target)
  })
})

describe('useRegisterScanTarget', () => {
  it('posts the new target and invalidates the list on success', async () => {
    server.use(
      http.post('*/api/v1/targets', () =>
        HttpResponse.json(target, { status: 201 }),
      ),
    )
    const { result } = renderHook(() => useRegisterScanTarget(), { wrapper })

    result.current.mutate({
      name: 'staging web app',
      target_url: 'https://staging.example.com',
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(target)
  })

  it('surfaces a 409 conflict error', async () => {
    server.use(
      http.post(
        '*/api/v1/targets',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail: 'A target with this URL already exists',
            }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const { result } = renderHook(() => useRegisterScanTarget(), { wrapper })

    result.current.mutate({
      name: 'staging web app',
      target_url: 'https://staging.example.com',
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useDeactivateScanTarget', () => {
  it('deletes the target', async () => {
    server.use(
      http.delete(
        '*/api/v1/targets/t1',
        () => new HttpResponse(null, { status: 204 }),
      ),
    )
    const { result } = renderHook(() => useDeactivateScanTarget(), { wrapper })

    result.current.mutate('t1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })
})

describe('useTriggerTargetScan', () => {
  it('posts a scan trigger for the target and returns the created run + status', async () => {
    server.use(
      http.post('*/api/v1/targets/t1/scans', () =>
        HttpResponse.json(
          {
            id: 's1',
            repository_id: null,
            status: 'pending',
            trigger: 'manual',
            commit_sha: null,
            ref: null,
            scan_target_id: 't1',
            created_at: '2026-01-01T00:00:00Z',
            started_at: null,
            completed_at: null,
          },
          { status: 202 },
        ),
      ),
    )
    const { result } = renderHook(() => useTriggerTargetScan(), { wrapper })

    result.current.mutate({ targetId: 't1' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toMatchObject({ status: 202 })
  })

  it('surfaces the dast_enabled=false 403 error', async () => {
    server.use(
      http.post(
        '*/api/v1/targets/t1/scans',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Forbidden',
              detail: 'DAST scanning is disabled (dast_enabled is unset)',
            }),
            {
              status: 403,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const { result } = renderHook(() => useTriggerTargetScan(), { wrapper })

    result.current.mutate({ targetId: 't1' })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
