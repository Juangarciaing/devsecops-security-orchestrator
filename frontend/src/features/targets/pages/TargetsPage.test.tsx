import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import type { ScanRun } from '@/features/scans/types'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { ScanTarget } from '../types'
import { TargetsPage } from './TargetsPage'

function target(id: string, overrides: Partial<ScanTarget> = {}): ScanTarget {
  return {
    id,
    name: `target-${id}`,
    target_url: `https://target-${id}.example.com`,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function scan(overrides: Partial<ScanRun> = {}): ScanRun {
  return {
    id: 's1',
    repository_id: null,
    status: 'completed',
    trigger: 'manual',
    commit_sha: null,
    ref: null,
    scan_target_id: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    ...overrides,
  }
}

function mockScans(scans: ScanRun[] = []) {
  server.use(http.get('*/api/v1/scans', () => HttpResponse.json(scans)))
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TargetsPage />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('TargetsPage', () => {
  it('shows a table skeleton while targets are loading', async () => {
    server.use(
      http.get('*/api/v1/targets', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when targets fail to load', async () => {
    server.use(
      http.get('*/api/v1/targets', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows an empty state with a register action when there are no targets', async () => {
    server.use(http.get('*/api/v1/targets', () => HttpResponse.json([])))
    mockScans()
    renderPage()

    expect(await screen.findByText(/no scan targets/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /register target/i }),
    ).toBeInTheDocument()
  })

  it('lists targets and paginates with previous/next controls', async () => {
    const targets = Array.from({ length: 12 }, (_, i) => target(String(i)))
    server.use(http.get('*/api/v1/targets', () => HttpResponse.json(targets)))
    mockScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('target-0')
    expect(screen.queryByText('target-10')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 10 of 12')).toBeInTheDocument()

    const next = screen.getByRole('button', { name: /^next$/i })
    await user.click(next)

    expect(await screen.findByText('target-10')).toBeInTheDocument()
    expect(screen.queryByText('target-0')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^next$/i })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /^previous$/i }))
    expect(await screen.findByText('target-0')).toBeInTheDocument()
  })

  it('filters targets by search text', async () => {
    server.use(
      http.get('*/api/v1/targets', () =>
        HttpResponse.json([
          target('1', { name: 'public-web' }),
          target('2', { name: 'internal-api' }),
        ]),
      ),
    )
    mockScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('public-web')
    await user.type(
      screen.getByRole('textbox', { name: /search targets/i }),
      'internal',
    )

    expect(screen.queryByText('public-web')).not.toBeInTheDocument()
    expect(screen.getByText('internal-api')).toBeInTheDocument()
  })

  it('filters targets by status', async () => {
    server.use(
      http.get('*/api/v1/targets', () =>
        HttpResponse.json([
          target('1', { name: 'active-target', is_active: true }),
          target('2', { name: 'inactive-target', is_active: false }),
        ]),
      ),
    )
    mockScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('active-target')
    await user.click(screen.getByRole('button', { name: 'Inactive' }))

    expect(screen.queryByText('active-target')).not.toBeInTheDocument()
    expect(screen.getByText('inactive-target')).toBeInTheDocument()
  })

  it('derives the stat strip from targets and scans', async () => {
    server.use(
      http.get('*/api/v1/targets', () =>
        HttpResponse.json([
          target('1', { is_active: true }),
          target('2', { is_active: false }),
        ]),
      ),
    )
    mockScans([scan({ scan_target_id: '1', status: 'running' })])
    renderPage()

    await screen.findByText('target-1')

    function tileValue(label: string) {
      const tile = screen.getByText(label).closest('[data-slot="stat-tile"]')
      return within(tile as HTMLElement).getByText(/^\d+$/).textContent
    }

    expect(tileValue('Total targets')).toBe('2')
    expect(tileValue('Active targets')).toBe('1')
    expect(tileValue('Scans running')).toBe('1')
    expect(tileValue('Never scanned')).toBe('1')
  })
})
