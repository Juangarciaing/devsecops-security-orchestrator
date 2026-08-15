import type { Finding } from './types'

// Pure predicate driving the severity-stripe/CriticalCue pairing on a
// Findings row (Req7). Product decision: critical-and-OPEN only — a
// resolved/suppressed critical, or an open high, MUST NOT trigger the
// stripe (critical-or-high was explicitly rejected). Each Findings row
// already represents exactly one Finding, so this takes a single finding
// rather than a list — ScanDetail's `features/scans/severity.ts` (PR5)
// reuses this same predicate via `findings.some(hasOpenCritical)` when a
// row must aggregate over several findings.
export function hasOpenCritical(finding: Finding): boolean {
  return finding.severity === 'critical' && finding.status === 'open'
}
