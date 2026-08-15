import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { TriggerTargetScanButton } from './TriggerTargetScanButton'

const mockNavigate = vi.fn()
vi.mock('react-router', async () => {
  const actual =
    await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('sonner', async () => {
  const actual = await vi.importActual<typeof import('sonner')>('sonner')
  return {
    ...actual,
    toast: { ...actual.toast, info: vi.fn(), error: vi.fn() },
  }
})

function renderButton() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </MemoryRouter>
    )
  }
  return render(<TriggerTargetScanButton targetId="t1" />, {
    wrapper: Wrapper,
  })
}

describe('TriggerTargetScanButton', () => {
  afterEach(() => {
    mockNavigate.mockClear()
    vi.mocked(toast.info).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('navigates to the new scan detail page on a successful (new) trigger', async () => {
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
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scans/s1'))
    expect(toast.info).not.toHaveBeenCalled()
  })

  it('navigates and notifies when a scan is already in flight (200 idempotent)', async () => {
    server.use(
      http.post('*/api/v1/targets/t1/scans', () =>
        HttpResponse.json(
          {
            id: 's2',
            repository_id: null,
            status: 'running',
            trigger: 'manual',
            commit_sha: null,
            ref: null,
            scan_target_id: 't1',
            created_at: '2026-01-01T00:00:00Z',
            started_at: '2026-01-01T00:00:01Z',
            completed_at: null,
          },
          { status: 200 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scans/s2'))
    expect(toast.info).toHaveBeenCalled()
  })

  it('shows an inline error when dast_enabled is false (403)', async () => {
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
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    expect(
      await screen.findByText('DAST scanning is disabled (dast_enabled is unset)'),
    ).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('forwards the selected scanner_type when the user picks one', async () => {
    let capturedBody: unknown
    server.use(
      http.post('*/api/v1/targets/t1/scans', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json(
          {
            id: 's3',
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
        )
      }),
    )
    const user = userEvent.setup()
    renderButton()

    await user.selectOptions(screen.getByLabelText(/scanner type/i), 'dast')
    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scans/s3'))
    expect(capturedBody).toMatchObject({ scanner_type: 'dast' })
  })

  it('omits scanner_type when none is selected (backward compatible)', async () => {
    let capturedBody: unknown
    server.use(
      http.post('*/api/v1/targets/t1/scans', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json(
          {
            id: 's4',
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
        )
      }),
    )
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByRole('button', { name: /trigger scan/i }))

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scans/s4'))
    expect(capturedBody).not.toHaveProperty('scanner_type')
  })
})
