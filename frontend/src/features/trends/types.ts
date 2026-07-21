import type { FindingSeverity } from '@/features/findings/types'

// Mirrors `application/dto/trends.py`: `TrendPoint.introduced` and
// `RepositoryTrendsRead.current_open` only carry keys for severities with a
// non-zero count — absent severities imply 0. Never assume every
// `FindingSeverity` key is present.
export type SeverityCounts = Partial<Record<FindingSeverity, number>>

export interface TrendPoint {
  scan_run_id: string
  occurred_at: string
  commit_sha: string
  introduced: SeverityCounts
}

export interface RepositoryTrends {
  repository_id: string
  points: TrendPoint[]
  current_open: SeverityCounts
}
