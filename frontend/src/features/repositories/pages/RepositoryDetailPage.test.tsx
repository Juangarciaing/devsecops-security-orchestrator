import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { delay, http, HttpResponse, type JsonBodyType } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { RepositoryDetailPage } from './RepositoryDetailPage'

const repo = {
  id: 'r1',
  provider: 'github',
  owner: 'acme',
  name: 'widgets',
  clone_url: 'https://github.com/acme/widgets.git',
  default_branch: 'main',
  has_credential: false,
  credential_kind: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderPage(id: string) {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={[`/repositories/${id}`]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Routes>
            <Route
              path="/repositories/:id"
              element={<RepositoryDetailPage />}
            />
          </Routes>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

// Reduces the state-coverage/stripe tests below to a single overridable call
// per scenario instead of re-declaring all 5 routes each time (the
// pre-existing tests above keep their own full inline handlers, unchanged).
type Behavior<T> = { data: T } | { status: number } | 'pending'

function route<T extends JsonBodyType>(url: string, behavior: Behavior<T>) {
  if (behavior === 'pending') {
    return http.get(url, async () => {
      await delay('infinite')
      return HttpResponse.json(null)
    })
  }
  if ('status' in behavior) {
    return http.get(url, () => new HttpResponse(null, { status: behavior.status }))
  }
  return http.get(url, () => HttpResponse.json(behavior.data))
}

const trendsOf = (current_open: Record<string, number>) => ({
  repository_id: 'r1',
  points: [],
  current_open,
})
const DEFAULT_DIFF = {
  repository_id: 'r1',
  latest_run: null,
  baseline_run: null,
  added: [],
  resolved: [],
  carried: [],
}
const DEFAULT_POLICY = {
  repository_id: 'r1',
  verdict: 'pass',
  blocking_severities: ['critical', 'high'],
  violating_counts: {},
}

function repoHandlers(overrides: {
  repository?: Behavior<typeof repo>
  scans?: Behavior<unknown[]>
  trends?: Behavior<ReturnType<typeof trendsOf>>
} = {}) {
  return [
    route('*/api/v1/repositories/r1', overrides.repository ?? { data: repo }),
    route('*/api/v1/scans', overrides.scans ?? { data: [] }),
    route(
      '*/api/v1/repositories/r1/trends',
      overrides.trends ?? { data: trendsOf({}) },
    ),
    route('*/api/v1/repositories/r1/diff', { data: DEFAULT_DIFF }),
    route('*/api/v1/repositories/r1/policy-check', { data: DEFAULT_POLICY }),
  ]
}

describe('RepositoryDetailPage', () => {
  it('shows repository info, a trigger-scan action, and an empty scan history state', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
      http.get('*/api/v1/scans', () => HttpResponse.json([])),
      http.get('*/api/v1/repositories/r1/trends', () =>
        HttpResponse.json({
          repository_id: 'r1',
          points: [],
          current_open: {},
        }),
      ),
      http.get('*/api/v1/repositories/r1/diff', () =>
        HttpResponse.json({
          repository_id: 'r1',
          latest_run: null,
          baseline_run: null,
          added: [],
          resolved: [],
          carried: [],
        }),
      ),
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json({
          repository_id: 'r1',
          verdict: 'pass',
          blocking_severities: ['critical', 'high'],
          violating_counts: {},
        }),
      ),
    )
    renderPage('r1')

    expect(await screen.findByText('acme/widgets')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /trigger scan/i }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/no scans/i)).toBeInTheDocument()
    expect(
      await screen.findByText(/no completed scans yet/i),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/not enough scan history/i),
    ).toBeInTheDocument()
    expect(await screen.findByText(/pass/i)).toBeInTheDocument()
  })

  it('lists prior scans for the repository, filtered from the full scan list', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
      http.get('*/api/v1/scans', () =>
        HttpResponse.json([
          {
            id: 's1',
            repository_id: 'r1',
            status: 'completed',
            trigger: 'manual',
            commit_sha: 'main',
            ref: 'main',
            created_at: '2026-01-01T00:00:00Z',
            started_at: '2026-01-01T00:00:01Z',
            completed_at: '2026-01-01T00:00:10Z',
          },
          {
            id: 's2',
            repository_id: 'other-repo',
            status: 'completed',
            trigger: 'manual',
            commit_sha: 'main',
            ref: 'main',
            created_at: '2026-01-01T00:00:00Z',
            started_at: null,
            completed_at: null,
          },
        ]),
      ),
      http.get('*/api/v1/repositories/r1/trends', () =>
        HttpResponse.json({
          repository_id: 'r1',
          points: [],
          current_open: {},
        }),
      ),
      http.get('*/api/v1/repositories/r1/diff', () =>
        HttpResponse.json({
          repository_id: 'r1',
          latest_run: null,
          baseline_run: null,
          added: [],
          resolved: [],
          carried: [],
        }),
      ),
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json({
          repository_id: 'r1',
          verdict: 'pass',
          blocking_severities: ['critical', 'high'],
          violating_counts: {},
        }),
      ),
    )
    renderPage('r1')

    expect(await screen.findByRole('link', { name: /view/i })).toHaveAttribute(
      'href',
      '/scans/s1',
    )
  })

  it('shows the diff panel sections once a baseline exists', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
      http.get('*/api/v1/scans', () => HttpResponse.json([])),
      http.get('*/api/v1/repositories/r1/trends', () =>
        HttpResponse.json({
          repository_id: 'r1',
          points: [],
          current_open: {},
        }),
      ),
      http.get('*/api/v1/repositories/r1/diff', () =>
        HttpResponse.json({
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
        }),
      ),
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json({
          repository_id: 'r1',
          verdict: 'fail',
          blocking_severities: ['critical', 'high'],
          violating_counts: { critical: 2 },
        }),
      ),
    )
    renderPage('r1')

    expect(await screen.findByText('Scan diff')).toBeInTheDocument()
    expect(await screen.findByText('Added')).toBeInTheDocument()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
    expect(screen.getByText('Carried')).toBeInTheDocument()
    expect(await screen.findByText(/fail/i)).toBeInTheDocument()
  })

  it('shows a not-found message for a missing repository', async () => {
    server.use(
      http.get(
        '*/api/v1/repositories/r1',
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
    renderPage('r1')

    expect(await screen.findByText(/repository not found/i)).toBeInTheDocument()
  })

  it('shows a loading skeleton while the repository is loading', async () => {
    server.use(...repoHandlers({ repository: 'pending' }))
    const { container } = renderPage('r1')

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with retry when the repository fails to load for a non-404 reason', async () => {
    server.use(...repoHandlers({ repository: { status: 500 } }))
    renderPage('r1')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByText(/could not load this repository/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows a scan-history skeleton while scans are loading', async () => {
    server.use(...repoHandlers({ scans: 'pending' }))
    const { container } = renderPage('r1')

    await screen.findByText('acme/widgets')
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with retry when scan history fails to load', async () => {
    server.use(...repoHandlers({ scans: { status: 500 } }))
    renderPage('r1')

    expect(
      await screen.findByText(/could not load scan history/i),
    ).toBeInTheDocument()
  })

  it('shows a trend-chart skeleton while trend data is loading', async () => {
    server.use(...repoHandlers({ trends: 'pending' }))
    const { container } = renderPage('r1')

    await screen.findByText('acme/widgets')
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with retry when trend data fails to load', async () => {
    server.use(...repoHandlers({ trends: { status: 500 } }))
    renderPage('r1')

    expect(
      await screen.findByText(/could not load trend data/i),
    ).toBeInTheDocument()
  })

  it('shows the severity stripe and non-color cue on the header card when the repository has open critical findings', async () => {
    server.use(...repoHandlers({ trends: { data: trendsOf({ critical: 2 }) } }))
    const { container } = renderPage('r1')

    await screen.findByText('acme/widgets')
    await waitFor(() => {
      expect(
        container.querySelector('[data-critical="true"]'),
      ).toBeInTheDocument()
    })
    expect(screen.getByText('Open critical finding')).toHaveClass('sr-only')
  })

  it('omits the severity stripe when the repository has no open critical findings', async () => {
    server.use(...repoHandlers())
    const { container } = renderPage('r1')

    await screen.findByText(/no completed scans yet/i)
    expect(
      container.querySelector('[data-critical="true"]'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Open critical finding')).not.toBeInTheDocument()
  })

  it('derives the stat strip from scan history and trend data', async () => {
    server.use(
      ...repoHandlers({
        scans: {
          data: [
            {
              id: 's1',
              repository_id: 'r1',
              status: 'completed',
              trigger: 'manual',
              commit_sha: 'main',
              ref: 'main',
              created_at: '2026-01-01T00:00:00Z',
              started_at: '2026-01-01T00:00:01Z',
              completed_at: '2026-01-01T00:00:10Z',
            },
            {
              id: 's2',
              repository_id: 'r1',
              status: 'running',
              trigger: 'manual',
              commit_sha: 'main',
              ref: 'main',
              created_at: '2026-01-02T00:00:00Z',
              started_at: '2026-01-02T00:00:01Z',
              completed_at: null,
            },
          ],
        },
        trends: { data: trendsOf({ critical: 2, high: 3 }) },
      }),
    )
    renderPage('r1')

    await screen.findByText('acme/widgets')

    function tileValue(label: string) {
      const tile = screen.getByText(label).closest('[data-slot="stat-tile"]')
      return within(tile as HTMLElement).getByText(/^\d+$/).textContent
    }

    expect(tileValue('Total scans')).toBe('2')
    expect(tileValue('Critical, open')).toBe('2')
    expect(tileValue('High, open')).toBe('3')
    const lastScanTile = screen.getByText('Last scan').closest('[data-slot="stat-tile"]')
    expect(within(lastScanTile as HTMLElement).getByText(/running/i)).toBeInTheDocument()
  })
})
