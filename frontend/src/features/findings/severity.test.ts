import { describe, expect, it } from 'vitest'
import type { Finding } from './types'
import { hasOpenCritical } from './severity'

// Matches the shape existing findings tests use (FindingsPage.test.tsx,
// FindingsTable.test.tsx) — kept in sync with `Finding` (types.ts).
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

// Req7: stripe/cue MUST render only when a finding is OPEN and CRITICAL —
// critical-or-high was explicitly rejected as the product decision, and a
// resolved critical MUST NOT trigger it either.
describe('hasOpenCritical', () => {
  it('returns true for an open critical finding', () => {
    expect(
      hasOpenCritical(finding({ severity: 'critical', status: 'open' })),
    ).toBe(true)
  })

  it('returns false for a critical finding that is resolved (not open)', () => {
    expect(
      hasOpenCritical(finding({ severity: 'critical', status: 'resolved' })),
    ).toBe(false)
  })

  it('returns false for an open high-severity finding (critical-or-high was rejected)', () => {
    expect(
      hasOpenCritical(finding({ severity: 'high', status: 'open' })),
    ).toBe(false)
  })

  it('returns false for a suppressed critical finding', () => {
    expect(
      hasOpenCritical(finding({ severity: 'critical', status: 'suppressed' })),
    ).toBe(false)
  })
})
