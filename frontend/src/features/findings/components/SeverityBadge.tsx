import { Badge } from '@/shared/ui/badge'
import type { FindingSeverity } from '../types'

const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

const SEVERITY_VARIANT: Record<
  FindingSeverity,
  'destructive' | 'default' | 'secondary' | 'outline'
> = {
  critical: 'destructive',
  high: 'destructive',
  medium: 'default',
  low: 'outline',
  info: 'secondary',
}

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
  return (
    <Badge variant={SEVERITY_VARIANT[severity]} data-severity={severity}>
      {SEVERITY_LABEL[severity]}
    </Badge>
  )
}
