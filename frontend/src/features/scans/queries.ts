import {
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
} from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import { isTerminalScanStatus } from './types'
import type { ScanRun, ScanRunDetail, TriggerScanInput } from './types'

interface TriggerScanArgs extends TriggerScanInput {
  repositoryId: string
}

interface TriggerScanResult {
  run: ScanRun
  // 201/202 = a new scan run was created; 200 = an equivalent scan was
  // already in flight and this is the existing run (idempotent trigger).
  status: number
}

async function triggerScan({
  repositoryId,
  commit_sha,
  scanner_type,
}: TriggerScanArgs): Promise<TriggerScanResult> {
  const response = await apiClient.post<ScanRun>(
    `/api/v1/repositories/${repositoryId}/scans`,
    { commit_sha, scanner_type },
  )
  return { run: response.data, status: response.status }
}

export function useTriggerScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: triggerScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scans'] })
    },
  })
}

async function fetchScan(id: string): Promise<ScanRunDetail> {
  const { data } = await apiClient.get<ScanRunDetail>(`/api/v1/scans/${id}`)
  return data
}

// Pure predicate for the polling cadence (Req: Scan Status Polling): poll
// every 2500ms while the run is pending/running, stop once it reaches a
// terminal status. Exported so it can be unit tested without timers.
export function scanRefetchInterval(
  data: ScanRunDetail | undefined,
): number | false {
  if (!data) {
    return false
  }
  return isTerminalScanStatus(data.status) ? false : 2500
}

export function useScan(id: string) {
  return useQuery({
    queryKey: ['scans', id],
    queryFn: () => fetchScan(id),
    enabled: Boolean(id),
    refetchInterval: (query: Query<ScanRunDetail>) =>
      scanRefetchInterval(query.state.data),
  })
}

async function fetchScans(): Promise<ScanRun[]> {
  const { data } = await apiClient.get<ScanRun[]>('/api/v1/scans', {
    params: { limit: 100 },
  })
  return data
}

// `GET /api/v1/scans` has no `repository_id` filter server-side, so we fetch
// the (limited) recent list and filter client-side. Fine at MVP scale; see
// apply-progress deviations for the tracked gap if this needs a backend
// filter param later.
export function useRepositoryScans(repositoryId: string) {
  return useQuery({
    queryKey: ['scans', 'byRepository', repositoryId],
    queryFn: async () => {
      const scans = await fetchScans()
      return scans.filter((scan) => scan.repository_id === repositoryId)
    },
    enabled: Boolean(repositoryId),
  })
}
