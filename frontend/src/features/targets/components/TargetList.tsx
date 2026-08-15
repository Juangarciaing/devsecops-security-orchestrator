import { EmptyState } from '@/shared/components/EmptyState'
import type { ScanTarget } from '../types'
import { TargetCard } from './TargetCard'

export function TargetList({ targets }: { targets: ScanTarget[] }) {
  if (targets.length === 0) {
    return (
      <EmptyState
        title="No scan targets registered yet"
        description="Register one to get started."
      />
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
