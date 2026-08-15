import { hasOpenCritical } from '@/features/findings/severity'
import type { Finding } from '@/features/findings/types'

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
