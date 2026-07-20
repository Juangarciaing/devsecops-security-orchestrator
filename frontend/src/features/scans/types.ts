export type ScannerType =
  'sast' | 'dast' | 'sca' | 'secrets' | 'iac' | 'semgrep'

export type ScanRunStatus =
  'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type ScanTaskStatus =
  'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface ScanRun {
  id: string
  repository_id: string
  status: ScanRunStatus
  trigger: string
  commit_sha: string
  ref: string
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface ScanRunDetail extends ScanRun {
  task_status: ScanTaskStatus
  findings_count: number
}

export interface TriggerScanInput {
  commit_sha?: string
  scanner_type?: ScannerType
}

// A scan run's status is terminal (no further transitions expected) once it
// reaches one of these — polling stops here (Req: Scan Status Polling).
export const TERMINAL_SCAN_STATUSES: readonly ScanRunStatus[] = [
  'completed',
  'failed',
  'cancelled',
]

export function isTerminalScanStatus(status: ScanRunStatus): boolean {
  return TERMINAL_SCAN_STATUSES.includes(status)
}
