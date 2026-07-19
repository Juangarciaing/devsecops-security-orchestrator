import { Badge } from '@/shared/ui/badge'
import type { FindingStatus } from '../types'

const STATUS_LABEL: Record<FindingStatus, string> = {
  open: 'Open',
  resolved: 'Resolved',
  suppressed: 'Suppressed',
  false_positive: 'False positive',
}

const STATUS_VARIANT: Record<
  FindingStatus,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  open: 'destructive',
  resolved: 'outline',
  suppressed: 'secondary',
  false_positive: 'secondary',
}

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status]} data-status={status}>
      {STATUS_LABEL[status]}
    </Badge>
  )
}
