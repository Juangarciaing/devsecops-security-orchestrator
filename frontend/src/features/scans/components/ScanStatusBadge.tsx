import { Badge } from '@/shared/ui/badge'
import type { ScanRunStatus } from '../types'

const STATUS_LABEL: Record<ScanRunStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

// Each status is an outline badge whose border/text color is its own
// `--status-*` token (see frontend/src/index.css), checked for AA contrast
// against both `--background` and `--card`. Kept subdued relative to the
// filled SeverityBadge so run-state chips don't compete with severity chips.
export const STATUS_TOKEN_CLASSNAME: Record<ScanRunStatus, string> = {
  pending: 'border-status-pending text-status-pending',
  running: 'border-status-running text-status-running',
  completed: 'border-status-completed text-status-completed',
  failed: 'border-status-failed text-status-failed',
  cancelled: 'border-status-cancelled text-status-cancelled',
}

export function ScanStatusBadge({ status }: { status: ScanRunStatus }) {
  return (
    <Badge
      variant="outline"
      data-status={status}
      className={STATUS_TOKEN_CLASSNAME[status]}
    >
      {STATUS_LABEL[status]}
    </Badge>
  )
}
