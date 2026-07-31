import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiBaseUrl } from '@/shared/config'
import { getToken } from '@/shared/api/token'
import { isTerminalScanStatus } from './types'
import type { ScanRunStatus } from './types'

interface ScanStatusEventPayload {
  scan_run_id: string
  status: ScanRunStatus
  at: string
}

// `EventSource` cannot set an `Authorization` header, so the access token
// travels as a query-string parameter — the accepted D2 tradeoff from the
// design, bounded by the token's short expiry and mitigated by the
// header-preferred/query-fallback shape already implemented server-side.
function streamUrl(id: string, token: string): string {
  return `${apiBaseUrl}/api/v1/scans/${id}/events?access_token=${token}`
}

// Req: Real-Time Scan Status Push (design D-Frontend). `EventSource` is a
// refetch hint, never a data source: every `scan.status` message
// invalidates the `['scans', id]` query so the authenticated REST endpoint
// remains the sole source of scan data — the push payload is status-only
// and cannot construct a full `ScanRunDetail` (missing `task_status`/
// `findings_count`).
export function useScanEvents(id: string): { live: boolean } {
  const queryClient = useQueryClient()
  const [connection, setConnection] = useState<{ id: string; live: boolean }>(
    { id, live: false },
  )
  // Derived during render rather than reset via a synchronous setState call
  // at the top of the effect (React's recommended pattern for resetting
  // state when a prop changes — avoids an extra cascading render): once
  // `id` no longer matches the connection this state was captured for,
  // treat it as "not live" until a fresh `open`/`error` for the new id
  // updates it.
  const live = connection.id === id ? connection.live : false

  useEffect(() => {
    const token = getToken()
    if (!id || !token) {
      return
    }
    // Spec: an unsupported browser (no EventSource) falls back to polling
    // immediately, without ever throwing — `live` simply stays `false`.
    if (typeof EventSource === 'undefined') {
      return
    }

    const source = new EventSource(streamUrl(id, token))

    const handleOpen = () => setConnection({ id, live: true })
    const handleError = () => setConnection({ id, live: false })
    const handleStatus = (event: MessageEvent<string>) => {
      queryClient.invalidateQueries({ queryKey: ['scans', id] })
      try {
        const payload = JSON.parse(event.data) as ScanStatusEventPayload
        if (isTerminalScanStatus(payload.status)) {
          // Load-bearing, not defensive: the server-side close after a
          // *successful* stream is a clean close, which the UA will
          // reconnect from per the HTML spec. Without this explicit
          // client-side close, the page would loop reconnecting against a
          // finished scan.
          source.close()
          setConnection({ id, live: false })
        }
      } catch {
        // Malformed payload: rely on the next event, the heartbeat, or a
        // connection error to recover — never crash the hook on bad data.
      }
    }

    source.addEventListener('open', handleOpen)
    source.addEventListener('error', handleError)
    source.addEventListener('scan.status', handleStatus as EventListener)

    return () => {
      source.removeEventListener('open', handleOpen)
      source.removeEventListener('error', handleError)
      source.removeEventListener(
        'scan.status',
        handleStatus as EventListener,
      )
      // Unconditional: React 18/19 StrictMode double-invokes effects in
      // dev, so an idempotent close here is what prevents every mount from
      // opening two streams.
      source.close()
    }
  }, [id, queryClient])

  return { live }
}
