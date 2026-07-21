import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { Finding } from '@/features/findings/types'
import type { RepositoryDiff } from '../types'
import { DiffPanel } from './DiffPanel'

function makeFinding(id: string, overrides: Partial<Finding> = {}): Finding {
  return {
    id,
    scan_task_id: 't1',
    severity: 'high',
    status: 'open',
    rule_id: 'generic-api-key',
    title: `Finding ${id}`,
    fingerprint: `fp-${id}`,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    description: null,
    file_path: 'src/config.ts',
    line_number: 12,
    raw_evidence: { secret: 'sk-***' },
    snippet: 'const key = "sk-***"',
    repository_id: 'r1',
    first_seen_scan_run_id: 's1',
    last_seen_scan_run_id: 's1',
    ...overrides,
  }
}

function renderPanel() {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <DiffPanel repositoryId="r1" />
    </QueryClientProvider>,
  )
}

describe('DiffPanel', () => {
  it('renders added, resolved, and carried sections when a baseline exists', async () => {
    const diff: RepositoryDiff = {
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
      added: [makeFinding('added-1')],
      resolved: [makeFinding('resolved-1')],
      carried: [makeFinding('carried-1')],
    }
    server.use(
      http.get('*/api/v1/repositories/r1/diff', () => HttpResponse.json(diff)),
    )
    renderPanel()

    expect(await screen.findByText('Finding added-1')).toBeInTheDocument()
    expect(screen.getByText('Finding resolved-1')).toBeInTheDocument()
    expect(screen.getByText('Finding carried-1')).toBeInTheDocument()
    expect(screen.getByText('Added')).toBeInTheDocument()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
    expect(screen.getByText('Carried')).toBeInTheDocument()
  })

  it('shows a not-enough-history message when baseline_run is null, instead of erroring', async () => {
    const diff: RepositoryDiff = {
      repository_id: 'r1',
      latest_run: {
        scan_run_id: 's1',
        occurred_at: '2026-01-01T00:00:00Z',
        commit_sha: 'abc123',
      },
      baseline_run: null,
      added: [makeFinding('added-1')],
      resolved: [],
      carried: [],
    }
    server.use(
      http.get('*/api/v1/repositories/r1/diff', () => HttpResponse.json(diff)),
    )
    renderPanel()

    expect(
      await screen.findByText(/not enough scan history/i),
    ).toBeInTheDocument()
    expect(screen.queryByText('Finding added-1')).not.toBeInTheDocument()
  })

  it('renders a member-redacted finding without leaking sensitive fields', async () => {
    const diff: RepositoryDiff = {
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
      added: [
        makeFinding('added-1', {
          file_path: null,
          line_number: null,
          raw_evidence: null,
          snippet: null,
        }),
      ],
      resolved: [],
      carried: [],
    }
    server.use(
      http.get('*/api/v1/repositories/r1/diff', () => HttpResponse.json(diff)),
    )
    renderPanel()

    expect(await screen.findByText('Finding added-1')).toBeInTheDocument()
    expect(screen.queryByText(/src\/config\.ts/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /details/i }),
    ).not.toBeInTheDocument()
  })
})
