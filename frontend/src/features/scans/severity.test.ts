import { describe, expect, it } from 'vitest'
import type { Finding } from '@/features/findings/types'
import { hasOpenCriticalFindings, openSeverityCounts } from './severity'

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 'f1',
    scan_task_id: 't1',
    severity: 'critical',
    status: 'open',
    rule_id: 'generic-api-key',
    title: 'Hardcoded API key',
    fingerprint: 'abc123',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    description: null,
    file_path: null,
    line_number: null,
    raw_evidence: null,
    snippet: null,
    repository_id: 'r1',
    first_seen_scan_run_id: 's1',
    last_seen_scan_run_id: 's1',
    ...overrides,
  }
}

describe('hasOpenCriticalFindings', () => {
  it('is true when an open critical finding exists', () => {
    expect(hasOpenCriticalFindings([finding()])).toBe(true)
  })

  it('is false when the only critical finding is resolved', () => {
    expect(
      hasOpenCriticalFindings([finding({ status: 'resolved' })]),
    ).toBe(false)
  })
})

describe('openSeverityCounts', () => {
  it('counts open findings grouped by severity', () => {
    const counts = openSeverityCounts([
      finding({ id: 'f1', severity: 'critical', status: 'open' }),
      finding({ id: 'f2', severity: 'critical', status: 'open' }),
      finding({ id: 'f3', severity: 'high', status: 'open' }),
      finding({ id: 'f4', severity: 'high', status: 'resolved' }),
    ])

    expect(counts).toEqual({ critical: 2, high: 1 })
  })

  it('returns an empty object when there are no open findings', () => {
    expect(
      openSeverityCounts([finding({ status: 'suppressed' })]),
    ).toEqual({})
  })
})
