import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { Finding, FindingFilters } from './types'

async function fetchScanFindings(scanRunId: string): Promise<Finding[]> {
  const { data } = await apiClient.get<Finding[]>(
    `/api/v1/scans/${scanRunId}/findings`,
  )
  return data
}

export function useScanFindings(scanRunId: string) {
  return useQuery({
    queryKey: ['scans', scanRunId, 'findings'],
    queryFn: () => fetchScanFindings(scanRunId),
    enabled: Boolean(scanRunId),
  })
}

async function fetchFindings(filters: FindingFilters): Promise<Finding[]> {
  const { data } = await apiClient.get<Finding[]>('/api/v1/findings', {
    params: filters,
  })
  return data
}

// `GET /api/v1/findings` genuinely supports server-side limit/offset/filters
// (unlike PR2's repositories/scans client-side workarounds) — pass filters
// straight through as query params; axios drops `undefined` values.
export function useFindings(filters: FindingFilters) {
  return useQuery({
    queryKey: ['findings', filters],
    queryFn: () => fetchFindings(filters),
  })
}

async function suppressFinding(findingId: string): Promise<Finding> {
  const { data } = await apiClient.post<Finding>(
    `/api/v1/findings/${findingId}/suppress`,
  )
  return data
}

// Refetch-based, not optimistic (design decision) — invalidate both the
// cross-run `findings` family and the `scans` family (covers
// ['scans', id, 'findings'] scan-scoped lists) on success.
export function useSuppressFinding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: suppressFinding,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['findings'] })
      queryClient.invalidateQueries({ queryKey: ['scans'] })
    },
  })
}

async function unsuppressFinding(findingId: string): Promise<Finding> {
  const { data } = await apiClient.post<Finding>(
    `/api/v1/findings/${findingId}/unsuppress`,
  )
  return data
}

export function useUnsuppressFinding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: unsuppressFinding,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['findings'] })
      queryClient.invalidateQueries({ queryKey: ['scans'] })
    },
  })
}
