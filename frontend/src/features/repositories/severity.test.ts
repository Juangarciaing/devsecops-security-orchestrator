import { describe, expect, it } from 'vitest'
import type { Finding } from '@/features/findings/types'
import type { RepositoryTrends } from '@/features/trends/types'
import {
  hasOpenCriticalFindings,
  openSeverityCounts,
  repositoryHasOpenCritical,
} from './severity'

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
    repository_id: 'r1',
    first_seen_scan_run_id: null,
    last_seen_scan_run_id: null,
    ...overrides,
  }
}

function trends(
  current_open: RepositoryTrends['current_open'],
): RepositoryTrends {
  return { repository_id: 'r1', points: [], current_open }
}

// Req7/D5: RepositoryDetail's header-card stripe (moved from per-scan rows —
// ScanRun carries no severity data) derives from `useRepoTrends`'s
// present-moment `current_open` snapshot, not a historical `introduced`
// point.
describe('hasOpenCriticalFindings', () => {
  it('returns true when current_open has an open critical count', () => {
    expect(hasOpenCriticalFindings(trends({ critical: 2 }))).toBe(true)
  })

  it('returns false when current_open.critical is explicitly 0', () => {
    expect(hasOpenCriticalFindings(trends({ critical: 0 }))).toBe(false)
  })

  it('returns false when the repository has no findings tracked at all (empty current_open)', () => {
    expect(hasOpenCriticalFindings(trends({}))).toBe(false)
  })

  it('returns false when trends is undefined (query not yet successful)', () => {
    expect(hasOpenCriticalFindings(undefined)).toBe(false)
  })
})

describe('repositoryHasOpenCritical', () => {
  it('returns true when the repository has an open critical finding', () => {
    const findings = [finding({ repository_id: 'r1', severity: 'critical', status: 'open' })]
    expect(repositoryHasOpenCritical(findings, 'r1')).toBe(true)
  })

  it('returns false for a resolved critical finding', () => {
    const findings = [finding({ repository_id: 'r1', severity: 'critical', status: 'resolved' })]
    expect(repositoryHasOpenCritical(findings, 'r1')).toBe(false)
  })

  it('returns false for an open high finding (critical-or-high rejected)', () => {
    const findings = [finding({ repository_id: 'r1', severity: 'high', status: 'open' })]
    expect(repositoryHasOpenCritical(findings, 'r1')).toBe(false)
  })

  it('ignores findings belonging to a different repository', () => {
    const findings = [finding({ repository_id: 'r2', severity: 'critical', status: 'open' })]
    expect(repositoryHasOpenCritical(findings, 'r1')).toBe(false)
  })
})

describe('openSeverityCounts', () => {
  it('counts open findings by severity for the given repository', () => {
    const findings = [
      finding({ repository_id: 'r1', severity: 'critical', status: 'open' }),
      finding({ repository_id: 'r1', severity: 'critical', status: 'open' }),
      finding({ repository_id: 'r1', severity: 'high', status: 'open' }),
    ]
    expect(openSeverityCounts(findings, 'r1')).toEqual({ critical: 2, high: 1 })
  })

  it('excludes non-open findings', () => {
    const findings = [
      finding({ repository_id: 'r1', severity: 'critical', status: 'resolved' }),
      finding({ repository_id: 'r1', severity: 'critical', status: 'suppressed' }),
    ]
    expect(openSeverityCounts(findings, 'r1')).toEqual({})
  })

  it('excludes findings belonging to a different repository', () => {
    const findings = [finding({ repository_id: 'r2', severity: 'critical', status: 'open' })]
    expect(openSeverityCounts(findings, 'r1')).toEqual({})
  })

  it('returns an empty object when there are no findings at all', () => {
    expect(openSeverityCounts([], 'r1')).toEqual({})
  })
})
