import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { AdminUser, CreateUserInput } from './types'

async function fetchUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>('/api/v1/users')
  return data
}

export function useUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: fetchUsers,
  })
}

async function createUser(input: CreateUserInput): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>('/api/v1/users', input)
  return data
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}
