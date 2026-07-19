import { useState } from 'react'
import { Button } from '@/shared/ui/button'
import { RegisterRepositoryDialog } from '../components/RegisterRepositoryDialog'
import { RepositoryList } from '../components/RepositoryList'
import { useRepositories } from '../queries'

const PAGE_SIZE = 10

export function RepositoriesPage() {
  const repositoriesQuery = useRepositories()
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Repositories</h2>
        <RegisterRepositoryDialog />
      </div>

      {repositoriesQuery.isPending ? (
        <p className="text-muted-foreground">Loading repositories…</p>
      ) : null}

      {repositoriesQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load repositories.
        </p>
      ) : null}

      {repositoriesQuery.isSuccess ? (
        <>
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
