export interface ScanTarget {
  id: string
  name: string
  target_url: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface RegisterScanTargetInput {
  name: string
  target_url: string
}

export interface UpdateScanTargetInput {
  name?: string
  target_url?: string
}
