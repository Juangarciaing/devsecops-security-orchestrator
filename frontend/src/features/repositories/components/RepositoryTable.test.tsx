import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { Finding } from '@/features/findings/types'
import type { ScanRun } from '@/features/scans/types'
import type { CodeRepository } from '../types'
import { RepositoryTable } from './RepositoryTable'

const repo: CodeRepository = {
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

function renderTable(
  repositories: CodeRepository[],
  findings: Finding[] = [],
  scans: ScanRun[] = [],
) {
  return render(
    <MemoryRouter>
      <RepositoryTable
        repositories={repositories}
        findings={findings}
        scans={scans}
      />
    </MemoryRouter>,
  )
}

describe('RepositoryTable', () => {
  it('renders a row per repository with a link to its detail page', () => {
    renderTable([repo, { ...repo, id: 'r2', name: 'gadgets' }])

    expect(screen.getByText('acme/widgets')).toBeInTheDocument()
    expect(screen.getByText('acme/gadgets')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'acme/widgets' }),
    ).toHaveAttribute('href', '/repositories/r1')
  })

  it('shows an empty-state message with when there are no repositories', () => {
    renderTable([])

    expect(screen.getByText(/no repositories/i)).toBeInTheDocument()
  })

  it('shows a "no credential" badge when the repository has none', () => {
    renderTable([repo])

    const badge = screen.getByText(/no credential/i)
    expect(badge).toHaveAttribute('data-credential', 'absent')
  })

  it('shows a credential badge reflecting a configured credential', () => {
    renderTable([
      { ...repo, has_credential: true, credential_kind: 'personal_access_token' },
    ])

    expect(screen.getByText(/personal access token/i)).toHaveAttribute(
      'data-credential',
      'present',
    )
  })

  it('shows "Not scanned yet" when the repository has no scans', () => {
    renderTable([repo])

    expect(screen.getByText('Not scanned yet')).toBeInTheDocument()
  })

  it("shows the latest scan's status badge when a scan exists", () => {
    const scans: ScanRun[] = [
      {
        id: 's1',
        repository_id: 'r1',
        status: 'running',
        trigger: 'manual',
        commit_sha: null,
        ref: null,
        scan_target_id: null,
        created_at: '2026-01-01T00:00:00Z',
        started_at: null,
        completed_at: null,
      },
    ]
    renderTable([repo], [], scans)

    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('applies the severity stripe and shows "No open findings" is replaced by dots when there is an open critical finding', () => {
    const findings: Finding[] = [
      {
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
        repository_id: 'r1',
        first_seen_scan_run_id: null,
        last_seen_scan_run_id: null,
      },
    ]
    renderTable([repo], findings)

    const cell = screen.getByText('acme/widgets').closest('td')
    expect(cell).toHaveAttribute('data-critical', 'true')
    expect(screen.getByText('Open critical finding')).toHaveClass('sr-only')
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.queryByText('No open findings')).not.toBeInTheDocument()
  })
})
