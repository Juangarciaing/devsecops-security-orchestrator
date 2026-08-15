import { describe, expect, it } from 'vitest'
import type { RepositoryTrends } from '@/features/trends/types'
import { hasOpenCriticalFindings } from './severity'

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
