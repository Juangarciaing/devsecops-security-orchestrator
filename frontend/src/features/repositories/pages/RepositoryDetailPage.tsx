import { useParams } from 'react-router'
import { isAxiosError } from 'axios'
import { Badge } from '@/shared/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { ScanHistoryTable } from '@/features/scans/components/ScanHistoryTable'
import { TriggerScanButton } from '@/features/scans/components/TriggerScanButton'
import { useRepositoryScans } from '@/features/scans/queries'
import { DeleteRepositoryButton } from '../components/DeleteRepositoryButton'
import { useRepository } from '../queries'

export function RepositoryDetailPage() {
  const { id } = useParams<{ id: string }>()
  const repositoryQuery = useRepository(id ?? '')
  const scansQuery = useRepositoryScans(id ?? '')

  if (repositoryQuery.isPending) {
    return <p className="text-muted-foreground">Loading repository…</p>
  }

  if (repositoryQuery.isError) {
    const notFound =
      isAxiosError(repositoryQuery.error) &&
      repositoryQuery.error.response?.status === 404
    return (
      <p role="alert" className="text-sm text-destructive">
        {notFound ? 'Repository not found.' : 'Could not load this repository.'}
      </p>
    )
  }

  const repository = repositoryQuery.data

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>
            {repository.owner}/{repository.name}
          </CardTitle>
          <Badge variant="outline">{repository.provider}</Badge>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <span className="text-sm text-muted-foreground">
            Default branch: {repository.default_branch}
          </span>
          <div className="flex items-center gap-2">
            <TriggerScanButton repositoryId={repository.id} />
            <DeleteRepositoryButton repositoryId={repository.id} />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2">
        <h3 className="text-lg font-semibold">Scan history</h3>
        {scansQuery.isPending ? (
          <p className="text-muted-foreground">Loading scan history…</p>
        ) : null}
        {scansQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Could not load scan history.
          </p>
        ) : null}
        {scansQuery.isSuccess ? (
          <ScanHistoryTable scans={scansQuery.data} />
        ) : null}
      </div>
    </div>
  )
}
