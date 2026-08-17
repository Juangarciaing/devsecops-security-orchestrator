import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import type { Finding } from '@/features/findings/types'
import type { ScanRun } from '@/features/scans/types'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { CodeRepository } from '../types'
import { RepositoriesPage } from './RepositoriesPage'

function repo(id: string, overrides: Partial<CodeRepository> = {}): CodeRepository {
  return {
    id,
    provider: 'github',
    owner: 'acme',
    name: `repo-${id}`,
    clone_url: `https://github.com/acme/repo-${id}.git`,
    default_branch: 'main',
    has_credential: false,
    credential_kind: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 'f1',
    scan_task_id: 't1',
    severity: 'critical',
    status: 'open',
    rule_id: 'rule',
    title: 'title',
    fingerprint: 'fp',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    description: null,
    file_path: null,
    line_number: null,
    raw_evidence: null,
    snippet: null,
    repository_id: null,
    first_seen_scan_run_id: null,
    last_seen_scan_run_id: null,
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

function mockFindingsAndScans(findings: Finding[] = [], scans: ScanRun[] = []) {
  server.use(
    http.get('*/api/v1/findings', () => HttpResponse.json(findings)),
    http.get('*/api/v1/scans', () => HttpResponse.json(scans)),
  )
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RepositoriesPage />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('RepositoriesPage', () => {
  it('shows a table skeleton while repositories are loading', async () => {
    server.use(
      http.get('*/api/v1/repositories', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when repositories fail to load', async () => {
    server.use(
      http.get('*/api/v1/repositories', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows an empty state with a register action when there are no repositories', async () => {
    server.use(http.get('*/api/v1/repositories', () => HttpResponse.json([])))
    mockFindingsAndScans()
    renderPage()

    expect(await screen.findByText(/no repositories/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /register repository/i }),
    ).toBeInTheDocument()
  })

  it('lists repositories and paginates with previous/next controls', async () => {
    const repositories = Array.from({ length: 12 }, (_, i) => repo(String(i)))
    server.use(
      http.get('*/api/v1/repositories', () => HttpResponse.json(repositories)),
    )
    mockFindingsAndScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('acme/repo-0')
    expect(screen.queryByText('acme/repo-10')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 10 of 12')).toBeInTheDocument()

    const next = screen.getByRole('button', { name: /^next$/i })
    await user.click(next)

    expect(await screen.findByText('acme/repo-10')).toBeInTheDocument()
    expect(screen.queryByText('acme/repo-0')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^next$/i })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /^previous$/i }))
    expect(await screen.findByText('acme/repo-0')).toBeInTheDocument()
  })

  it('filters repositories by search text', async () => {
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([
          repo('1', { owner: 'acme', name: 'api-gateway' }),
          repo('2', { owner: 'acme', name: 'payments-service' }),
        ]),
      ),
    )
    mockFindingsAndScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('acme/api-gateway')
    await user.type(
      screen.getByRole('textbox', { name: /search repositories/i }),
      'payments',
    )

    expect(screen.queryByText('acme/api-gateway')).not.toBeInTheDocument()
    expect(screen.getByText('acme/payments-service')).toBeInTheDocument()
  })

  it('filters repositories by provider', async () => {
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([
          repo('1', { provider: 'github', name: 'gh-repo' }),
          repo('2', { provider: 'gitlab', name: 'gl-repo' }),
        ]),
      ),
    )
    mockFindingsAndScans()
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('acme/gh-repo')
    await user.click(screen.getByRole('button', { name: 'GitLab' }))

    expect(screen.queryByText('acme/gh-repo')).not.toBeInTheDocument()
    expect(screen.getByText('acme/gl-repo')).toBeInTheDocument()
  })

  it('derives the stat strip from repositories, findings, and scans', async () => {
    server.use(
      http.get('*/api/v1/repositories', () =>
        HttpResponse.json([
          repo('1', { has_credential: true, credential_kind: 'personal_access_token' }),
          repo('2', { has_credential: false }),
        ]),
      ),
    )
    mockFindingsAndScans(
      [finding({ repository_id: '1', severity: 'critical', status: 'open' })],
      [scan({ repository_id: '2', status: 'running' })],
    )
    renderPage()

    await screen.findByText('acme/repo-1')

    function tileValue(label: string) {
      const tile = screen.getByText(label).closest('[data-slot="stat-tile"]')
      return within(tile as HTMLElement).getByText(/^\d+$/).textContent
    }

    expect(tileValue('Total repos')).toBe('2')
    expect(tileValue('Critical, open')).toBe('1')
    expect(tileValue('Scans running')).toBe('1')
    expect(tileValue('Missing credential')).toBe('1')
  })
})
