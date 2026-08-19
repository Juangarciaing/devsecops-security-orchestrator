import { hasOpenCritical } from '@/features/findings/severity'
import type { Finding } from '@/features/findings/types'
import type { RepositoryTrends, SeverityCounts } from '@/features/trends/types'

// Pure predicate driving the severity-stripe/CriticalCue pairing on the
// RepositoryDetail header card (Req7). Design D5 deviation (accepted):
// the stripe moved from per-scan rows to the header card because `ScanRun`
// carries no severity data — `current_open` is the repository's exact,
// present-moment open-critical snapshot from the already-mounted
// `useRepoTrends`, never a historical `introduced` point. Optional
// chaining short-circuits the whole expression when `trends` itself is
// undefined (query pending/error), and an absent/zero `critical` key both
// resolve to `false` via the `?? 0` default.
export function hasOpenCriticalFindings(
  trends: RepositoryTrends | undefined,
): boolean {
  return (trends?.current_open.critical ?? 0) > 0
}

// Severity-stripe predicate for the Repositories LIST table. Unlike the
// detail header above, the list page already has the full `Finding[]` on
// hand (Req: repositories list mockup) rather than a per-repo trends
// snapshot — filter to this repository's findings and reuse the same
// single-finding predicate findings/severity.ts defines, mirroring how
// features/scans/severity.ts wraps it for ScanDetail instead of
// re-deriving "open and critical" locally.
export function repositoryHasOpenCritical(
  findings: Finding[],
  repositoryId: string,
): boolean {
  return findings
    .filter((finding) => finding.repository_id === repositoryId)
    .some(hasOpenCritical)
}

// Per-repository open-finding severity breakdown driving the list table's
// severity-dot cluster cell. Counts OPEN findings only (status !== 'open'
// findings — resolved/suppressed/false_positive — never appear in the
// cluster), grouped by severity. Absent severities are omitted rather than
// zero-filled, matching the `SeverityCounts` (Partial<Record<...>>)
// convention `features/trends/types.ts` already establishes.
export function openSeverityCounts(
  findings: Finding[],
  repositoryId: string,
): SeverityCounts {
  const counts: SeverityCounts = {}
  for (const finding of findings) {
    if (finding.repository_id !== repositoryId || finding.status !== 'open') {
      continue
    }
    counts[finding.severity] = (counts[finding.severity] ?? 0) + 1
  }
  return counts
}
