import { useParams, Link } from 'react-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { ScanStatusBadge } from '../components/ScanStatusBadge'
import { useScan } from '../queries'

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const scanQuery = useScan(id ?? '')

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

  return (
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
  )
}
