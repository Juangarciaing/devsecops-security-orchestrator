import { useParams, Link } from 'react-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { FindingsTable } from '@/features/findings/components/FindingsTable'
import { useScanFindings } from '@/features/findings/queries'
import { ScanStatusBadge } from '../components/ScanStatusBadge'
import { isTerminalScanStatus } from '../types'
import { useScan } from '../queries'

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const scanQuery = useScan(id ?? '')
  const scanFindingsQuery = useScanFindings(
    scanQuery.data && isTerminalScanStatus(scanQuery.data.status)
      ? (id ?? '')
      : '',
  )

  if (scanQuery.isPending) {
    return <p className="text-muted-foreground">Loading scan…</p>
  }

  if (scanQuery.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load this scan.
      </p>
    )
  }

  const scan = scanQuery.data

  const showFindings = isTerminalScanStatus(scan.status)

  return (
    <div className="flex flex-col gap-4">
      <Card className="max-w-2xl">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Scan {scan.id}</CardTitle>
          <ScanStatusBadge status={scan.status} />
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
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

      {showFindings ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-lg font-semibold">Findings</h3>
          {scanFindingsQuery.isPending ? (
            <p className="text-muted-foreground">Loading findings…</p>
          ) : null}
          {scanFindingsQuery.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Could not load findings.
            </p>
          ) : null}
          {scanFindingsQuery.isSuccess ? (
            <FindingsTable findings={scanFindingsQuery.data} />
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
