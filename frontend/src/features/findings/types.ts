import type { ScannerType } from '@/features/scans/types'

export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export type FindingStatus =
  'open' | 'resolved' | 'suppressed' | 'false_positive'

export interface Finding {
  id: string
  scan_task_id: string
  severity: FindingSeverity
  status: FindingStatus
  rule_id: string
  title: string
  fingerprint: string
  created_at: string
  updated_at: string
  description: string | null
  // Redacted (nulled by the backend) for the `member` role — never assume
  // these are present. Render conditionally (Req: Redaction-Safe Rendering).
  file_path: string | null
  line_number: number | null
  raw_evidence: Record<string, unknown> | null
  snippet: string | null
  repository_id: string | null
  first_seen_scan_run_id: string | null
  last_seen_scan_run_id: string | null
}

export interface FindingFilters {
  severity?: FindingSeverity
  status?: FindingStatus
  repository_id?: string
  scanner_type?: ScannerType
  limit?: number
  offset?: number
}

// Pure predicate driving `SuppressButton`'s label/action (Req: Finding
// Suppression) — suppressed findings unsuppress, everything else suppresses.
export function isSuppressed(status: FindingStatus): boolean {
  return status === 'suppressed'
}
