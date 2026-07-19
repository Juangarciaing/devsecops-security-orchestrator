import { useMutation, useQuery } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import { setToken } from '@/shared/api/token'
import type { CurrentUser, LoginCredentials, LoginResponse } from './types'

async function login(credentials: LoginCredentials): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>(
    '/api/v1/auth/login',
    credentials,
  )
  return data
}

export function useLogin() {
  return useMutation({
    mutationFn: async (credentials: LoginCredentials) => {
      const response = await login(credentials)
      setToken(response.access_token)
      return response
    },
  })
}

async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>('/api/v1/auth/me')
  return data
}

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: fetchCurrentUser,
    enabled,
    retry: false,
  })
}
