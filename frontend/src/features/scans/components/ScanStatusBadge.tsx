import { Badge } from '@/shared/ui/badge'
import type { ScanRunStatus } from '../types'

const STATUS_LABEL: Record<ScanRunStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const STATUS_VARIANT: Record<
  ScanRunStatus,
  'secondary' | 'default' | 'destructive' | 'outline'
> = {
  pending: 'secondary',
  running: 'default',
  completed: 'default',
  failed: 'destructive',
  cancelled: 'outline',
}

export function ScanStatusBadge({ status }: { status: ScanRunStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} data-status={status}>
      {STATUS_LABEL[status]}
    </Badge>
  )
}
