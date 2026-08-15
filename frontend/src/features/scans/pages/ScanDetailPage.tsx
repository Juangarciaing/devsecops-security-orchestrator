import { useParams, Link } from 'react-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { CardGridSkeleton } from '@/shared/components/CardGridSkeleton'
import { CriticalCue, SeverityStripe } from '@/shared/components/SeverityStripe'
import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { FindingsTable } from '@/features/findings/components/FindingsTable'
import { useScanFindings } from '@/features/findings/queries'
import { ScanStatusBadge } from '../components/ScanStatusBadge'
import { hasOpenCriticalFindings } from '../severity'
import { isTerminalScanStatus } from '../types'
import { useScan } from '../queries'

// Matches FindingsTable's own header (Severity, Rule ID, Title, Status,
// Location, action column) so the skeleton's shape doesn't shift on load.
const FINDINGS_COLUMN_COUNT = 6

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const scanQuery = useScan(id ?? '')
  const scanFindingsQuery = useScanFindings(
    scanQuery.data && isTerminalScanStatus(scanQuery.data.status)
      ? (id ?? '')
      : '',
  )

  if (scanQuery.isPending) {
    return <CardGridSkeleton count={1} />
  }

  if (scanQuery.isError) {
    return (
      <ErrorState
        description="Could not load this scan."
        onRetry={() => scanQuery.refetch()}
      />
    )
  }

  const scan = scanQuery.data

  const showFindings = isTerminalScanStatus(scan.status)
  // Req7/D5 (revised): `false` while findings are pending/errored/not yet
  // fetched (non-terminal scan) — `scanFindingsQuery.data` is `undefined`
  // in all of those cases, so `?? []` short-circuits to inactive.
  const critical = hasOpenCriticalFindings(scanFindingsQuery.data ?? [])

  return (
    <div className="flex flex-col gap-4">
      <SeverityStripe active={critical}>
        <Card className="max-w-2xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Scan {scan.id}</CardTitle>
            <div className="flex items-center gap-2">
              <CriticalCue active={critical} />
              <ScanStatusBadge status={scan.status} />
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-body">
            <p>
              <span className="text-muted-foreground">Repository: </span>
              <Link
                to={`/repositories/${scan.repository_id}`}
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                {scan.repository_id}
              </Link>
            </p>
            <p>
              <span className="text-muted-foreground">Ref: </span>
              {scan.ref}
            </p>
            <p>
              <span className="text-muted-foreground">Trigger: </span>
              {scan.trigger}
            </p>
            <p>
              <span className="text-muted-foreground">Created: </span>
              {new Date(scan.created_at).toLocaleString()}
            </p>
            {scan.status === 'failed' ? (
              <p role="alert" className="text-destructive">
                Scan failed. Findings may be incomplete.
              </p>
            ) : null}
            {scan.status === 'completed' || scan.status === 'failed' ? (
              <p>
                <span className="text-muted-foreground">Findings: </span>
                {scan.findings_count}
              </p>
            ) : (
              <p className="text-muted-foreground">Scan in progress…</p>
            )}
          </CardContent>
        </Card>
      </SeverityStripe>

      {showFindings ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-subheading">Findings</h3>
          {scanFindingsQuery.isPending ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Rule ID</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableSkeleton columns={FINDINGS_COLUMN_COUNT} />
            </Table>
          ) : null}
          {scanFindingsQuery.isError ? (
            <ErrorState
              description="Could not load findings."
              onRetry={() => scanFindingsQuery.refetch()}
            />
          ) : null}
          {scanFindingsQuery.isSuccess ? (
            <FindingsTable findings={scanFindingsQuery.data} />
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
