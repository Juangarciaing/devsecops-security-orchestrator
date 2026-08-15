import { useState } from 'react'
import { Button } from '@/shared/ui/button'
import { WebhookDeliveriesTable } from '../components/WebhookDeliveriesTable'
import { useWebhookDeliveries } from '../queries'

const PAGE_SIZE = 20

// Admin-only audit view over the append-only `webhook_deliveries` log
// (design D8/D9) — mirrors `FindingsPage`'s real server-side pagination.
export function WebhookDeliveriesPage() {
  const [offset, setOffset] = useState(0)

  const deliveriesQuery = useWebhookDeliveries({ limit: PAGE_SIZE, offset })
  const deliveries = deliveriesQuery.data ?? []
  const hasNextPage = deliveries.length === PAGE_SIZE

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">Webhook deliveries audit</h2>

      {deliveriesQuery.isPending ? (
        <p className="text-muted-foreground">Loading deliveries…</p>
      ) : null}
      {deliveriesQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load webhook deliveries.
        </p>
      ) : null}
      {deliveriesQuery.isSuccess && deliveries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
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
