import { describe, expect, it } from 'vitest'
import type { ScanRun } from '@/features/scans/types'
import { latestScanForRepository } from './lastScan'

function scan(overrides: Partial<ScanRun> = {}): ScanRun {
  return {
    id: 's1',
    repository_id: 'r1',
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

describe('latestScanForRepository', () => {
  it('returns the most recent scan for the repository', () => {
    const scans = [
      scan({ id: 'old', repository_id: 'r1', created_at: '2026-01-01T00:00:00Z' }),
      scan({ id: 'new', repository_id: 'r1', created_at: '2026-01-03T00:00:00Z' }),
      scan({ id: 'mid', repository_id: 'r1', created_at: '2026-01-02T00:00:00Z' }),
    ]
    expect(latestScanForRepository(scans, 'r1')?.id).toBe('new')
  })

  it('ignores scans belonging to a different repository', () => {
    const scans = [scan({ id: 'other', repository_id: 'r2' })]
    expect(latestScanForRepository(scans, 'r1')).toBeUndefined()
  })

  it('ignores scan-target (DAST) runs with a null repository_id', () => {
    const scans = [
      scan({ id: 'dast', repository_id: null, scan_target_id: 'target-1' }),
    ]
    expect(latestScanForRepository(scans, 'r1')).toBeUndefined()
  })

  it('returns undefined when there are no scans at all', () => {
    expect(latestScanForRepository([], 'r1')).toBeUndefined()
  })
})
