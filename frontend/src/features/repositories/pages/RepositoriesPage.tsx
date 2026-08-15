import { useState } from 'react'
import { useFindings } from '@/features/findings/queries'
import { useScans } from '@/features/scans/queries'
import { CardGridSkeleton } from '@/shared/components/CardGridSkeleton'
import { ErrorState } from '@/shared/components/ErrorState'
import { OnboardingChecklist } from '@/shared/components/OnboardingChecklist'
import { Button } from '@/shared/ui/button'
import { RegisterRepositoryDialog } from '../components/RegisterRepositoryDialog'
import { RepositoryList } from '../components/RepositoryList'
import { useRepositories } from '../queries'

const PAGE_SIZE = 10

export function RepositoriesPage() {
  const repositoriesQuery = useRepositories()
  const scansQuery = useScans()
  const findingsQuery = useFindings({ limit: 1 })
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-heading">Repositories</h2>
        <RegisterRepositoryDialog />
      </div>

      {repositoriesQuery.isPending ? <CardGridSkeleton /> : null}

      {repositoriesQuery.isError ? (
        <ErrorState
          description="Could not load repositories."
          onRetry={() => repositoriesQuery.refetch()}
        />
      ) : null}

      {repositoriesQuery.isSuccess ? (
        <>
          <OnboardingChecklist
            hasRepository={repositoriesQuery.data.length > 0}
            hasCompletedScan={
              scansQuery.data?.some((scan) => scan.status === 'completed') ??
              false
            }
            hasFinding={(findingsQuery.data?.length ?? 0) > 0}
          />
          <RepositoryList
            repositories={repositoriesQuery.data.slice(0, visibleCount)}
          />
          {visibleCount < repositoriesQuery.data.length ? (
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
