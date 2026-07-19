import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { ScanDetailPage } from './ScanDetailPage'

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
})
