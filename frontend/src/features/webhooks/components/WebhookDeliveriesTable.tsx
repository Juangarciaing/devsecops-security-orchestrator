import { Badge } from '@/shared/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import type { WebhookDelivery } from '../types'

const EMPTY = '—'

export function WebhookDeliveriesTable({
  deliveries,
}: {
  deliveries: WebhookDelivery[]
}) {
  return (
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
      <TableBody>
        {deliveries.map((delivery) => (
          <TableRow key={delivery.id}>
            <TableCell>
              {new Date(delivery.received_at).toLocaleString()}
            </TableCell>
            <TableCell>{delivery.event_type ?? EMPTY}</TableCell>
            <TableCell>
              <Badge
                variant={
                  delivery.outcome === 'accepted' ? 'outline' : 'secondary'
                }
              >
                {delivery.outcome}
              </Badge>
            </TableCell>
            <TableCell>
              {delivery.signature_valid ? 'Valid' : 'Invalid'}
            </TableCell>
            <TableCell>{delivery.repository_full_name ?? EMPTY}</TableCell>
            <TableCell className="font-mono text-xs">
              {delivery.ref ?? EMPTY} / {delivery.commit_sha ?? EMPTY}
            </TableCell>
            <TableCell>{delivery.source_ip ?? EMPTY}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
