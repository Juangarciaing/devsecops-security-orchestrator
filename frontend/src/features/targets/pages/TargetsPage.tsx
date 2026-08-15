import { useState } from 'react'
import { CardGridSkeleton } from '@/shared/components/CardGridSkeleton'
import { ErrorState } from '@/shared/components/ErrorState'
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
        <h2 className="text-heading">Scan targets</h2>
        <RegisterTargetDialog />
      </div>

      {targetsQuery.isPending ? <CardGridSkeleton /> : null}

      {targetsQuery.isError ? (
        <ErrorState
          description="Could not load scan targets."
          onRetry={() => targetsQuery.refetch()}
        />
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
