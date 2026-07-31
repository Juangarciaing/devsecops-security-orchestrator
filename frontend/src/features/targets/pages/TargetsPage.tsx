import { useState } from 'react'
import { Button } from '@/shared/ui/button'
import { RegisterTargetDialog } from '../components/RegisterTargetDialog'
import { TargetList } from '../components/TargetList'
import { useScanTargets } from '../queries'

const PAGE_SIZE = 10

export function TargetsPage() {
  const targetsQuery = useScanTargets()
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Scan targets</h2>
        <RegisterTargetDialog />
      </div>

      {targetsQuery.isPending ? (
        <p className="text-muted-foreground">Loading scan targets…</p>
      ) : null}

      {targetsQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load scan targets.
        </p>
      ) : null}

      {targetsQuery.isSuccess ? (
        <>
          <TargetList targets={targetsQuery.data.slice(0, visibleCount)} />
          {visibleCount < targetsQuery.data.length ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Load more
            </Button>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
