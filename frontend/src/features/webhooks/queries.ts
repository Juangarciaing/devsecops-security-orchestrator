import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { WebhookDelivery, WebhookDeliveryFilters } from './types'

async function fetchWebhookDeliveries(
  filters: WebhookDeliveryFilters,
): Promise<WebhookDelivery[]> {
  const { data } = await apiClient.get<WebhookDelivery[]>(
    '/api/v1/webhooks/deliveries',
    { params: filters },
  )
  return data
}

// `GET /api/v1/webhooks/deliveries` is admin-gated and supports
// server-side limit/offset (design D8) — same shape as
// `features/findings`'s real pagination, unlike PR2's client-side
// workarounds.
export function useWebhookDeliveries(filters: WebhookDeliveryFilters) {
  return useQuery({
    queryKey: ['webhookDeliveries', filters],
    queryFn: () => fetchWebhookDeliveries(filters),
  })
}
