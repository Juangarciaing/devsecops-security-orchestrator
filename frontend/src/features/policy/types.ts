import type { FindingSeverity } from '@/features/findings/types'
import type { SeverityCounts } from '@/features/trends/types'

// Mirrors `application/dto/policy.py`'s `RepositoryPolicyRead.verdict`.
export type PolicyVerdict = 'pass' | 'fail'

// Mirrors `application/dto/policy.py`'s `RepositoryPolicyRead`.
// `violating_counts` is SPARSE and scoped to `blocking_severities` only
// (currently `critical`/`high`) — a severity absent from the dict means
// zero open findings of that severity. `MEDIUM`/`LOW`/`INFO` open counts
// are intentionally never surfaced here since they never affect `verdict`.
export interface RepositoryPolicy {
  repository_id: string
  verdict: PolicyVerdict
  blocking_severities: FindingSeverity[]
  violating_counts: SeverityCounts
}
