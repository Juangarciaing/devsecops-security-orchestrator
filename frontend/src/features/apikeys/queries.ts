import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { ApiKey, ApiKeyCreatedResponse } from './types'

const API_KEYS_QUERY_KEY = ['apiKeys'] as const

async function fetchApiKeys(): Promise<ApiKey[]> {
  // The backend scopes this to the caller (`get_current_user`, not
  // `require_role`) — every key returned already belongs to the caller.
  const { data } = await apiClient.get<ApiKey[]>('/api/v1/auth/api-keys')
  return data
}

export function useApiKeys() {
  return useQuery({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: fetchApiKeys,
  })
}

async function issueApiKey(): Promise<ApiKeyCreatedResponse> {
  const { data } = await apiClient.post<ApiKeyCreatedResponse>(
    '/api/v1/auth/api-keys',
  )
  return data
}

export function useIssueApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: issueApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY })
    },
  })
}

async function revokeApiKey(keyId: string): Promise<ApiKey> {
  // Backend returns 200 ApiKeyRead (not 204) with is_active=false/revoked_at
  // set — see design D8, verified against auth.py:79-96.
  const { data } = await apiClient.post<ApiKey>(
    `/api/v1/auth/api-keys/${keyId}/revoke`,
  )
  return data
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY })
    },
  })
}
