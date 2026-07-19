import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken } from '@/shared/api/token'
import { routes } from './router'

function renderApp() {
  const queryClient = createTestQueryClient()
  const memoryRouter = createMemoryRouter(routes, {
    initialEntries: ['/login'],
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={memoryRouter} />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

const repository = {
  id: 'r1',
  provider: 'github' as const,
  owner: 'acme',
  name: 'gitleaks-live-fixture',
  clone_url: 'https://github.com/acme/gitleaks-live-fixture.git',
  default_branch: 'main',
  credential_ref: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
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

const openFinding = {
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
  // Member-role redaction — must render safely.
  file_path: null,
  line_number: null,
  raw_evidence: null,
  snippet: null,
  repository_id: 'r1',
  first_seen_scan_run_id: 's1',
  last_seen_scan_run_id: 's1',
}

// End-to-end MSW-backed walk of the full golden path (Req: task 3.8):
// login -> repositories -> trigger scan -> poll to completion -> findings
// table -> suppress a finding.
describe('golden path', () => {
  afterEach(() => {
    clearToken()
    vi.useRealTimers()
  })

  it('walks login through scan completion and finding suppression', async () => {
    // Fake timers from the very start (shouldAdvanceTime keeps async
    // findBy*/waitFor calls working) so the scan poll's `setInterval` is
    // scheduled on the fake clock, not a real one — otherwise switching to
    // fake timers only right before the poll leaves the already-scheduled
    // real interval un-advanceable.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    server.use(
      http.post('*/api/v1/auth/login', () =>
        HttpResponse.json({ access_token: 'tok', token_type: 'bearer' }),
      ),
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u1',
          email: 'member@example.com',
          role: 'member',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
      http.get('*/api/v1/repositories', () => HttpResponse.json([repository])),
      http.post('*/api/v1/repositories/r1/scans', () =>
        HttpResponse.json({ ...baseScan, status: 'pending' }, { status: 202 }),
      ),
    )

    let scanCallCount = 0
    server.use(
      http.get('*/api/v1/scans/s1', () => {
        scanCallCount += 1
        const isTerminal = scanCallCount >= 2
        return HttpResponse.json({
          ...baseScan,
          status: isTerminal ? 'completed' : 'running',
          task_status: isTerminal ? 'completed' : 'running',
          completed_at: isTerminal ? '2026-01-01T00:05:00Z' : null,
          findings_count: isTerminal ? 1 : 0,
        })
      }),
    )

    renderApp()

    await user.type(screen.getByLabelText(/email/i), 'member@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-password')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    const repoLink = await screen.findByRole('link', {
      name: /acme\/gitleaks-live-fixture/i,
    })
    expect(repoLink).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    expect(await screen.findByText('Running')).toBeInTheDocument()

    let findingStatus: 'open' | 'suppressed' = 'open'
    server.use(
      http.get('*/api/v1/scans/s1/findings', () =>
        HttpResponse.json([{ ...openFinding, status: findingStatus }]),
      ),
      http.post('*/api/v1/findings/f1/suppress', () => {
        findingStatus = 'suppressed'
        return HttpResponse.json({ ...openFinding, status: 'suppressed' })
      }),
    )

    await vi.advanceTimersByTimeAsync(2500)

    expect(await screen.findByText('Completed')).toBeInTheDocument()

    expect(await screen.findByText('Hardcoded API key')).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^suppress$/i }))

    await waitFor(() =>
      expect(screen.getByText('Suppressed')).toBeInTheDocument(),
    )
  })
})
