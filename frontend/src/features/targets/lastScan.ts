import type { ScanRun } from '@/features/scans/types'

// Pure derivation for the Targets list table's "Last scan" column, mirroring
// `features/repositories/lastScan.ts#latestScanForRepository` — the most
// recent scan run for a given scan target, or undefined if none exists yet.
// `ScanRun.scan_target_id` is null for repository-scoped runs (backend
// D1/D5 — exactly one of repository_id/scan_target_id is set), so filtering
// by scan_target_id already excludes those.
export function latestScanForTarget(
  scans: ScanRun[],
  targetId: string,
): ScanRun | undefined {
  return scans
    .filter((scan) => scan.scan_target_id === targetId)
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0]
}
