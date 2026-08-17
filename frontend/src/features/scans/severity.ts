import { hasOpenCritical } from '@/features/findings/severity'
import type { Finding } from '@/features/findings/types'
import type { SeverityCounts } from '@/features/trends/types'

// Pure predicate driving the severity-stripe/CriticalCue pairing on the
// ScanDetail header card (Req7, revised D5). `ScanDetailPage` already
// queries `useScanFindings` for the full `Finding[]` once a scan reaches a
// terminal state, so — unlike the original D5 note on this page, which
// assumed no severity data was available — the open-critical signal IS
// derivable here without a new endpoint. Kept as a small local wrapper
// around findings/severity.ts's single-finding `hasOpenCritical` (rather
// than importing it directly into the page) to keep each feature's public
// surface clean, matching how `features/repositories/severity.ts` was kept
// separate from `features/findings/severity.ts` (PR5) instead of merged.
export function hasOpenCriticalFindings(findings: Finding[]): boolean {
  return findings.some(hasOpenCritical)
}

// Severity breakdown for the ScanDetail stat strip. Mirrors
// `features/repositories/severity.ts`'s `openSeverityCounts`, minus the
// repository-id filter: `useScanFindings` already scopes `findings` to this
// scan, so every open finding counts. Counts OPEN findings only, grouped by
// severity; absent severities are omitted (matches the `SeverityCounts`
// convention `features/trends/types.ts` establishes).
export function openSeverityCounts(findings: Finding[]): SeverityCounts {
  const counts: SeverityCounts = {}
  for (const finding of findings) {
    if (finding.status !== 'open') {
      continue
    }
    counts[finding.severity] = (counts[finding.severity] ?? 0) + 1
  }
  return counts
}
