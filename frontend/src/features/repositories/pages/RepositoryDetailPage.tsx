import { useParams } from 'react-router'
import { isAxiosError } from 'axios'
import { Badge } from '@/shared/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { Skeleton } from '@/shared/ui/skeleton'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { CardGridSkeleton } from '@/shared/components/CardGridSkeleton'
import { CriticalCue, SeverityStripe } from '@/shared/components/SeverityStripe'
import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { DiffPanel } from '@/features/diffing/components/DiffPanel'
import { PolicyGateBadge } from '@/features/policy/components/PolicyGateBadge'
import { ScanHistoryTable } from '@/features/scans/components/ScanHistoryTable'
import { TriggerScanButton } from '@/features/scans/components/TriggerScanButton'
import { useRepositoryScans } from '@/features/scans/queries'
import { TrendsChart } from '@/features/trends/components/TrendsChart'
import { useRepoTrends } from '@/features/trends/queries'
import { CredentialBadge } from '../components/CredentialBadge'
import { DeleteRepositoryButton } from '../components/DeleteRepositoryButton'
import { StatTile } from '../components/StatTile'
import { useRepository } from '../queries'
import { hasOpenCriticalFindings } from '../severity'

// Matches ScanHistoryTable's own header (Status, Ref, Triggered, action
// column) so the skeleton's shape doesn't shift on load.
const SCAN_HISTORY_COLUMN_COUNT = 4

export function RepositoryDetailPage() {
  const { id } = useParams<{ id: string }>()
  const repositoryQuery = useRepository(id ?? '')
  const scansQuery = useRepositoryScans(id ?? '')
  const trendsQuery = useRepoTrends(id ?? '')

  if (repositoryQuery.isPending) {
    return <CardGridSkeleton count={1} />
  }

  if (repositoryQuery.isError) {
    const notFound =
      isAxiosError(repositoryQuery.error) &&
      repositoryQuery.error.response?.status === 404
    return (
      <ErrorState
        description={
          notFound ? 'Repository not found.' : 'Could not load this repository.'
        }
        onRetry={notFound ? undefined : () => repositoryQuery.refetch()}
      />
    )
  }

  const repository = repositoryQuery.data
  // Req7/D5: the header-card stripe derives from the repository's exact,
  // present-moment `current_open` snapshot (useRepoTrends) — ScanRun
  // carries no severity data, so a per-scan-row stripe was not derivable
  // (design deviation, accepted). `false` while trends is pending/errored.
  const critical = hasOpenCriticalFindings(trendsQuery.data)

  const scans = scansQuery.data ?? []
  const currentOpen = trendsQuery.data?.current_open ?? {}
  const lastScan = scans.reduce<(typeof scans)[number] | undefined>(
    (latest, scan) =>
      !latest || scan.created_at > latest.created_at ? scan : latest,
    undefined,
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Total scans" value={scans.length} />
        <StatTile
          label="Critical, open"
          value={currentOpen.critical ?? 0}
          tone={(currentOpen.critical ?? 0) > 0 ? 'warning' : 'default'}
        />
        <StatTile label="High, open" value={currentOpen.high ?? 0} />
        <StatTile
          label="Last scan"
          value={
            lastScan ? (
              <span className="capitalize">{lastScan.status}</span>
            ) : (
              '—'
            )
          }
          tone={lastScan?.status === 'running' ? 'active' : 'default'}
        />
      </div>

      <SeverityStripe active={critical}>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>
              {repository.owner}/{repository.name}
            </CardTitle>
            <div className="flex items-center gap-2">
              <CriticalCue active={critical} />
              <Badge variant="outline">{repository.provider}</Badge>
              <CredentialBadge
                hasCredential={repository.has_credential}
                credentialKind={repository.credential_kind}
              />
              <PolicyGateBadge repositoryId={repository.id} />
            </div>
          </CardHeader>
          <CardContent className="flex items-center justify-between gap-4">
            <span className="text-meta text-muted-foreground">
              Default branch: {repository.default_branch}
            </span>
            <div className="flex items-center gap-2">
              <TriggerScanButton repositoryId={repository.id} />
              <DeleteRepositoryButton repositoryId={repository.id} />
            </div>
          </CardContent>
        </Card>
      </SeverityStripe>

      <div className="flex flex-col gap-2">
        <h3 className="text-subheading">Scan history</h3>
        {scansQuery.isPending ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Ref</TableHead>
                <TableHead>Triggered</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableSkeleton columns={SCAN_HISTORY_COLUMN_COUNT} />
          </Table>
        ) : null}
        {scansQuery.isError ? (
          <ErrorState
            description="Could not load scan history."
            onRetry={() => scansQuery.refetch()}
          />
        ) : null}
        {scansQuery.isSuccess ? (
          <ScanHistoryTable scans={scansQuery.data} />
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-subheading">Finding trends</h3>
        {trendsQuery.isPending ? <Skeleton className="h-[300px] w-full" /> : null}
        {trendsQuery.isError ? (
          <ErrorState
            description="Could not load trend data."
            onRetry={() => trendsQuery.refetch()}
          />
        ) : null}
        {trendsQuery.isSuccess ? (
          <TrendsChart points={trendsQuery.data.points} />
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-subheading">Scan diff</h3>
        <DiffPanel repositoryId={repository.id} />
      </div>
    </div>
  )
}
