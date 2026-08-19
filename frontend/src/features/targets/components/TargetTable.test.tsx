import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import type { ScanRun } from '@/features/scans/types'
import type { ScanTarget } from '../types'
import { TargetTable } from './TargetTable'

const target: ScanTarget = {
  id: 't1',
  name: 'public-web',
  target_url: 'https://public-web.example.com',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function mockCurrentUser(role: 'admin' | 'member') {
  setToken('a-valid-token')
  server.use(
    http.get('*/api/v1/auth/me', () =>
      HttpResponse.json({
        id: 'u1',
        email: 'a@b.com',
        role,
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
}

function renderTable(targets: ScanTarget[], scans: ScanRun[] = []) {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>{children}</AuthProvider>
        </QueryClientProvider>
      </MemoryRouter>
    )
  }
  return render(<TargetTable targets={targets} scans={scans} />, {
    wrapper: Wrapper,
  })
}

describe('TargetTable', () => {
  afterEach(() => {
    clearToken()
  })

  it('renders a row per target with its URL and active status', () => {
    mockCurrentUser('member')
    renderTable([
      target,
      {
        ...target,
        id: 't2',
        name: 'internal-api',
        target_url: 'https://internal-api.example.com',
      },
    ])

    expect(screen.getByText('public-web')).toBeInTheDocument()
    expect(screen.getByText('internal-api')).toBeInTheDocument()
    expect(
      screen.getByText('https://public-web.example.com'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('https://internal-api.example.com'),
    ).toBeInTheDocument()
    expect(screen.getAllByText('active')).toHaveLength(2)
  })

  it('shows an inactive badge for a deactivated target', () => {
    mockCurrentUser('member')
    renderTable([{ ...target, is_active: false }])

    expect(screen.getByText('inactive')).toBeInTheDocument()
  })

  it('shows an empty-state message when there are no targets', () => {
    mockCurrentUser('member')
    renderTable([])

    expect(screen.getByText(/no scan targets/i)).toBeInTheDocument()
  })

  it('shows "Not scanned yet" when the target has no scans', () => {
    mockCurrentUser('member')
    renderTable([target])

    expect(screen.getByText('Not scanned yet')).toBeInTheDocument()
  })

  it("shows the latest scan's status badge when a scan exists", () => {
    mockCurrentUser('member')
    const scans: ScanRun[] = [
      {
        id: 's1',
        repository_id: null,
        status: 'running',
        trigger: 'manual',
        commit_sha: null,
        ref: null,
        scan_target_id: 't1',
        created_at: '2026-01-01T00:00:00Z',
        started_at: null,
        completed_at: null,
      },
    ]
    renderTable([target], scans)

    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('always offers a trigger-scan action', async () => {
    mockCurrentUser('member')
    renderTable([target])

    expect(
      await screen.findByRole('button', { name: /trigger scan/i }),
    ).toBeInTheDocument()
  })

  it('hides the deactivate action for a member', async () => {
    mockCurrentUser('member')
    renderTable([target])

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /deactivate/i }),
      ).not.toBeInTheDocument(),
    )
  })

  it('shows the deactivate action for an admin', async () => {
    mockCurrentUser('admin')
    renderTable([target])

    expect(
      await screen.findByRole('button', { name: /deactivate/i }),
    ).toBeInTheDocument()
  })
})
