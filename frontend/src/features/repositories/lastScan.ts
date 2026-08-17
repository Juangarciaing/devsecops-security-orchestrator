import type { ScanRun } from '@/features/scans/types'

// Pure derivation for the Repositories list table's "Last scan" column: the
// most recent scan run for a given repository, or undefined if none exists
// yet. `ScanRun.repository_id` is null for scan-target (DAST) runs (backend
// D1/D5 — exactly one of repository_id/scan_target_id is set), so filtering
// by repository_id already excludes those without a separate
// scan_target_id check.
export function latestScanForRepository(
  scans: ScanRun[],
  repositoryId: string,
): ScanRun | undefined {
  return scans
    .filter((scan) => scan.repository_id === repositoryId)
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0]
}
