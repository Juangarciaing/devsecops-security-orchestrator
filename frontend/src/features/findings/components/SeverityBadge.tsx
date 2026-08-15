import { Badge } from '@/shared/ui/badge'
import type { FindingSeverity } from '../types'

const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

// Each severity is filled with its own `--severity-*`/`--severity-*-foreground`
// token pair (see frontend/src/index.css) so the five levels stay pairwise
// visually distinct and every label stays AA-legible against its own fill.
export const SEVERITY_TOKEN_CLASSNAME: Record<FindingSeverity, string> = {
  critical: 'bg-severity-critical text-severity-critical-foreground',
  high: 'bg-severity-high text-severity-high-foreground',
  medium: 'bg-severity-medium text-severity-medium-foreground',
  low: 'bg-severity-low text-severity-low-foreground',
  info: 'bg-severity-info text-severity-info-foreground',
}

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
  return (
    <Badge
      variant="outline"
      data-severity={severity}
      className={`border-transparent ${SEVERITY_TOKEN_CLASSNAME[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
    </Badge>
  )
}
