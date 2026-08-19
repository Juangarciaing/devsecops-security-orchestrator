import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface StatTileProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  tone?: 'default' | 'warning' | 'active'
}

const TONE_BORDER_CLASSNAME: Record<NonNullable<StatTileProps['tone']>, string> = {
  default: 'border-border',
  warning: 'border-severity-critical/40',
  active: 'border-status-running/40',
}

const TONE_VALUE_CLASSNAME: Record<NonNullable<StatTileProps['tone']>, string> = {
  default: 'text-foreground',
  warning: 'text-severity-critical',
  active: 'text-status-running',
}

// Repositories list page stat strip tile (Req: repositories list mockup).
// Purely presentational — the page computes `value`/`tone` from already
// -fetched repositories/findings/scans data, no new query here.
export function StatTile({ label, value, icon, tone = 'default' }: StatTileProps) {
  return (
    <div
      data-slot="stat-tile"
      className={cn(
        'flex flex-1 flex-col gap-2 rounded-lg border bg-card p-4',
        TONE_BORDER_CLASSNAME[tone],
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-meta text-muted-foreground uppercase tracking-wide">
          {label}
        </span>
        {icon}
      </div>
      <span
        className={cn(
          'text-2xl font-semibold tabular-nums',
          TONE_VALUE_CLASSNAME[tone],
        )}
      >
        {value}
      </span>
    </div>
  )
}
