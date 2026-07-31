import type { ScanTarget } from '../types'
import { TargetCard } from './TargetCard'

export function TargetList({ targets }: { targets: ScanTarget[] }) {
  if (targets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No scan targets registered yet. Register one to get started.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {targets.map((target) => (
        <TargetCard key={target.id} target={target} />
      ))}
    </div>
  )
}
