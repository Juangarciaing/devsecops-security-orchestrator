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
