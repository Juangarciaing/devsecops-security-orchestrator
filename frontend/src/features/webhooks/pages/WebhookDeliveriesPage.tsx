import { useState } from 'react'
import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { Button } from '@/shared/ui/button'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { WebhookDeliveriesTable } from '../components/WebhookDeliveriesTable'
import { useWebhookDeliveries } from '../queries'

const PAGE_SIZE = 20
// Matches WebhookDeliveriesTable's own header (Received, Event, Outcome,
// Signature, Repository, Ref / commit, Source IP) so the skeleton's shape
// doesn't shift on load.
const TABLE_COLUMN_COUNT = 7

// Admin-only audit view over the append-only `webhook_deliveries` log
// (design D8/D9) — mirrors `FindingsPage`'s real server-side pagination.
export function WebhookDeliveriesPage() {
  const [offset, setOffset] = useState(0)

  const deliveriesQuery = useWebhookDeliveries({ limit: PAGE_SIZE, offset })
  const deliveries = deliveriesQuery.data ?? []
  const hasNextPage = deliveries.length === PAGE_SIZE

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-heading">Webhook deliveries audit</h2>

      {deliveriesQuery.isPending ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Received</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead>Signature</TableHead>
              <TableHead>Repository</TableHead>
              <TableHead>Ref / commit</TableHead>
              <TableHead>Source IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableSkeleton columns={TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}
      {deliveriesQuery.isError ? (
        <ErrorState
          description="Could not load webhook deliveries."
          onRetry={() => deliveriesQuery.refetch()}
        />
      ) : null}
      {deliveriesQuery.isSuccess && deliveries.length === 0 ? (
        <p className="text-body text-muted-foreground">
          No webhook deliveries recorded yet.
        </p>
      ) : null}

      {deliveriesQuery.isSuccess && deliveries.length > 0 ? (
        <>
          <WebhookDeliveriesTable deliveries={deliveries} />
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={offset === 0}
              onClick={() =>
                setOffset((current) => Math.max(0, current - PAGE_SIZE))
              }
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!hasNextPage}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </>
      ) : null}
    </div>
  )
}
