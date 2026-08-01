import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, setToken } from '@/shared/api/token'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { ScanDetailPage } from './ScanDetailPage'

type FakeListener = (event: unknown) => void

// Hand-rolled fake `EventSource` — jsdom has no `EventSource` implementation
// (see `useScanEvents.test.tsx`) and this codebase avoids adding a test
// dependency for it. Duplicated locally rather than imported/shared, in
// keeping with this suite's existing per-file fixture convention (e.g.
// `baseScan` below is also duplicated from `queries.test.tsx`'s `scanRun`).
class FakeEventSource {
  static instances: FakeEventSource[] = []
  closed = false
  private listeners: Record<string, FakeListener[]> = {}

  constructor() {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: FakeListener): void {
    const bucket = this.listeners[type] ?? []
    bucket.push(listener)
    this.listeners[type] = bucket
  }

  removeEventListener(type: string, listener: FakeListener): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter(
      (registered) => registered !== listener,
    )
  }

  close(): void {
    this.closed = true
  }

  emit(type: string, event: unknown): void {
    for (const listener of this.listeners[type] ?? []) {
      listener(event)
    }
  }
}

function scanStatusEvent(status: string) {
  return {
    data: JSON.stringify({
      scan_run_id: 's1',
      status,
      at: '2026-01-01T00:05:00Z',
    }),
  }
}

function renderPage(id: string) {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={[`/scans/${id}`]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/scans/:id" element={<ScanDetailPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const baseScan = {
  id: 's1',
  repository_id: 'r1',
  trigger: 'manual',
  commit_sha: 'main',
  ref: 'main',
  created_at: '2026-01-01T00:00:00Z',
  started_at: '2026-01-01T00:00:01Z',
  completed_at: null as string | null,
}

describe('ScanDetailPage', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the current status and findings count while running', async () => {
    server.use(
      http.get('*/api/v1/scans/s1', () =>
        HttpResponse.json({
          ...baseScan,
          status: 'running',
          task_status: 'running',
          findings_count: 0,
        }),
      ),
    )
    renderPage('s1')

    expect(await screen.findByText('Running')).toBeInTheDocument()
  })

  it('shows a failure message once the scan fails', async () => {
    server.use(
      http.get('*/api/v1/scans/s1', () =>
        HttpResponse.json({
          ...baseScan,
          status: 'failed',
          task_status: 'failed',
          completed_at: '2026-01-01T00:05:00Z',
          findings_count: 0,
        }),
      ),
    )
    renderPage('s1')

    expect(await screen.findByText('Failed')).toBeInTheDocument()
    expect(screen.getByText(/scan failed/i)).toBeInTheDocument()
  })

  describe('polling', () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
    })

    it('polls every 2500ms while running and stops once completed', async () => {
      let callCount = 0
      server.use(
        http.get('*/api/v1/scans/s1', () => {
          callCount += 1
          const isTerminal = callCount >= 2
          return HttpResponse.json({
            ...baseScan,
            status: isTerminal ? 'completed' : 'running',
            task_status: isTerminal ? 'completed' : 'running',
            completed_at: isTerminal ? '2026-01-01T00:05:00Z' : null,
            findings_count: isTerminal ? 3 : 0,
          })
        }),
      )
      renderPage('s1')

      expect(await screen.findByText('Running')).toBeInTheDocument()
      expect(callCount).toBe(1)

      await vi.advanceTimersByTimeAsync(2500)
      expect(await screen.findByText('Completed')).toBeInTheDocument()
      expect(callCount).toBe(2)

      await vi.advanceTimersByTimeAsync(2500)
      await vi.advanceTimersByTimeAsync(2500)
      expect(callCount).toBe(2)
    })
  })

  // E2E-shaped coverage for the SSE push path and its polling fallback
  // (design D-Frontend, tasks 3.8/3.9): a live stream degrades the poll
  // interval to a 30s safety net rather than a 2500ms fast-poll, and a
  // dropped stream re-arms the original 2500ms polling — it never strands
  // the page.
  describe('realtime SSE', () => {
    beforeEach(() => {
      FakeEventSource.instances = []
      vi.stubGlobal('EventSource', FakeEventSource)
      setToken('test-token')
      vi.useFakeTimers({ shouldAdvanceTime: true })
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.unstubAllGlobals()
      clearToken()
    })

    it('reaches terminal status via the SSE push path while live, without a 2500ms poll firing', async () => {
      let callCount = 0
      server.use(
        http.get('*/api/v1/scans/s1', () => {
          callCount += 1
          const isTerminal = callCount >= 2
          return HttpResponse.json({
            ...baseScan,
            status: isTerminal ? 'completed' : 'running',
            task_status: isTerminal ? 'completed' : 'running',
            completed_at: isTerminal ? '2026-01-01T00:05:00Z' : null,
            findings_count: isTerminal ? 2 : 0,
          })
        }),
      )
      renderPage('s1')

      expect(await screen.findByText('Running')).toBeInTheDocument()
      expect(callCount).toBe(1)

      const source = FakeEventSource.instances[0]
      expect(source).toBeDefined()
      act(() => source.emit('open', {}))

      // SSE is live: the 30s safety-net interval is engaged, so a 2500ms
      // fast-poll must NOT fire an extra request.
      await vi.advanceTimersByTimeAsync(2500)
      expect(callCount).toBe(1)

      // The push event itself drives the transition, not a poll.
      act(() => source.emit('scan.status', scanStatusEvent('completed')))

      expect(await screen.findByText('Completed')).toBeInTheDocument()
      expect(callCount).toBe(2)
      // Client-side close on terminal status (load-bearing per D-Frontend).
      expect(source.closed).toBe(true)
    })

    it('re-arms 2500ms polling and still reaches terminal after the SSE stream errors mid-scan', async () => {
      let callCount = 0
      server.use(
        http.get('*/api/v1/scans/s1', () => {
          callCount += 1
          const isTerminal = callCount >= 3
          return HttpResponse.json({
            ...baseScan,
            status: isTerminal ? 'completed' : 'running',
            task_status: isTerminal ? 'completed' : 'running',
            completed_at: isTerminal ? '2026-01-01T00:05:00Z' : null,
            findings_count: isTerminal ? 1 : 0,
          })
        }),
      )
      renderPage('s1')

      expect(await screen.findByText('Running')).toBeInTheDocument()
      expect(callCount).toBe(1)

      const source = FakeEventSource.instances[0]
      act(() => source.emit('open', {}))

      // While live, the fast poll must not fire.
      await vi.advanceTimersByTimeAsync(2500)
      expect(callCount).toBe(1)

      // Kill the stream mid-scan (simulated connection error).
      act(() => source.emit('error', {}))

      // Fallback: 2500ms polling re-arms (design D-Frontend: not-live ⇒
      // today's 2500ms) and the page still reaches terminal — a dropped SSE
      // stream degrades gracefully, it does not strand the page.
      await vi.advanceTimersByTimeAsync(2500)
      expect(callCount).toBe(2)

      await vi.advanceTimersByTimeAsync(2500)
      expect(await screen.findByText('Completed')).toBeInTheDocument()
      expect(callCount).toBe(3)
    })
  })

  describe('findings table', () => {
    it('renders the findings table once the scan completes', async () => {
      server.use(
        http.get('*/api/v1/scans/s1', () =>
          HttpResponse.json({
            ...baseScan,
            status: 'completed',
            task_status: 'completed',
            completed_at: '2026-01-01T00:05:00Z',
            findings_count: 1,
          }),
        ),
        http.get('*/api/v1/scans/s1/findings', () =>
          HttpResponse.json([
            {
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
              file_path: null,
              line_number: null,
              raw_evidence: null,
              snippet: null,
              repository_id: 'r1',
              first_seen_scan_run_id: 's1',
              last_seen_scan_run_id: 's1',
            },
          ]),
        ),
      )
      renderPage('s1')

      expect(await screen.findByText('Hardcoded API key')).toBeInTheDocument()
    })

    it('does not render the findings table while the scan is still running', async () => {
      server.use(
        http.get('*/api/v1/scans/s1', () =>
          HttpResponse.json({
            ...baseScan,
            status: 'running',
            task_status: 'running',
            findings_count: 0,
          }),
        ),
      )
      renderPage('s1')

      await screen.findByText('Running')
      expect(screen.queryByText(/no findings/i)).not.toBeInTheDocument()
    })
  })
})
