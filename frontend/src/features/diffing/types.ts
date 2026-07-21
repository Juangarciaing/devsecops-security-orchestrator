import type { Finding } from '@/features/findings/types'

// Mirrors `application/dto/diff.py`'s `RunRef` — a minimal reference to one
// `ScanRun` (id, when it ran, and the commit it scanned).
export interface RunRef {
  scan_run_id: string
  occurred_at: string
  commit_sha: string
}

// Mirrors `application/dto/diff.py`'s `RepositoryDiffRead`. `latest_run` is
// `null` only when the repository has zero completed scan runs.
// `baseline_run` is `null` when fewer than 2 completed runs exist
// (insufficient history) — in that case `resolved`/`carried` are always
// empty and `added` contains every finding introduced by the sole run, if
// any. Every finding in `added`/`resolved`/`carried` is already redacted by
// the backend per the caller's role — same `Finding` shape/redaction
// contract as `features/findings`.
export interface RepositoryDiff {
  repository_id: string
  latest_run: RunRef | null
  baseline_run: RunRef | null
  added: Finding[]
  resolved: Finding[]
  carried: Finding[]
}
