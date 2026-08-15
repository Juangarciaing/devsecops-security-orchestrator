import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { ScanRun, ScannerType } from '@/features/scans/types'
import type { RegisterScanTargetInput, ScanTarget } from './types'

async function fetchScanTargets(): Promise<ScanTarget[]> {
  const { data } = await apiClient.get<ScanTarget[]>('/api/v1/targets')
  return data
}

export function useScanTargets() {
  return useQuery({
    queryKey: ['targets'],
    queryFn: fetchScanTargets,
  })
}

async function fetchScanTarget(id: string): Promise<ScanTarget> {
  const { data } = await apiClient.get<ScanTarget>(`/api/v1/targets/${id}`)
  return data
}

export function useScanTarget(id: string) {
  return useQuery({
    queryKey: ['targets', id],
    queryFn: () => fetchScanTarget(id),
    enabled: Boolean(id),
  })
}

async function registerScanTarget(
  input: RegisterScanTargetInput,
): Promise<ScanTarget> {
  const { data } = await apiClient.post<ScanTarget>('/api/v1/targets', input)
  return data
}

export function useRegisterScanTarget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: registerScanTarget,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['targets'] })
    },
  })
}

async function deactivateScanTarget(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/targets/${id}`)
}

export function useDeactivateScanTarget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deactivateScanTarget,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['targets'] })
    },
  })
}

interface TriggerTargetScanArgs {
  targetId: string
  // Forwarded on the request body for parity with the repository trigger
  // contract. The backend route currently hardcodes DAST for target scans
  // and does not read this field yet (PR8 deviation — see apply-progress).
  scanner_type?: ScannerType
}

interface TriggerTargetScanResult {
  run: ScanRun
  // 202 = a new scan run was created; 200 = an equivalent scan was already
  // in flight and this is the existing run (idempotent trigger) — mirrors
  // the repository trigger-scan contract exactly.
  status: number
}

async function triggerTargetScan({
  targetId,
  scanner_type,
}: TriggerTargetScanArgs): Promise<TriggerTargetScanResult> {
  const response = await apiClient.post<ScanRun>(
    `/api/v1/targets/${targetId}/scans`,
    { scanner_type },
  )
  return { run: response.data, status: response.status }
}

export function useTriggerTargetScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: triggerTargetScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scans'] })
    },
  })
}
