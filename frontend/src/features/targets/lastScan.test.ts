import { describe, expect, it } from 'vitest'
import type { ScanRun } from '@/features/scans/types'
import { latestScanForTarget } from './lastScan'

function scan(id: string, overrides: Partial<ScanRun> = {}): ScanRun {
  return {
    id,
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

describe('latestScanForTarget', () => {
  it('returns undefined when no scans exist for the target', () => {
    expect(latestScanForTarget([], 't1')).toBeUndefined()
  })

  it('returns the most recent scan for the target', () => {
    const scans = [
      scan('a', { scan_target_id: 't1', created_at: '2026-01-01T00:00:00Z' }),
      scan('b', { scan_target_id: 't1', created_at: '2026-01-02T00:00:00Z' }),
      scan('c', { scan_target_id: 't2', created_at: '2026-01-03T00:00:00Z' }),
    ]
    expect(latestScanForTarget(scans, 't1')?.id).toBe('b')
  })

  it('ignores repository-scoped scans even if scan_target_id is unset', () => {
    const scans = [scan('a', { repository_id: 'r1', scan_target_id: null })]
    expect(latestScanForTarget(scans, 't1')).toBeUndefined()
  })
})
