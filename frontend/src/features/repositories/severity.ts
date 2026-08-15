import type { RepositoryTrends } from '@/features/trends/types'

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
