import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { CodeRepository, RegisterRepositoryInput } from './types'

async function fetchRepositories(): Promise<CodeRepository[]> {
  const { data } = await apiClient.get<CodeRepository[]>('/api/v1/repositories')
  return data
}

export function useRepositories() {
  return useQuery({
    queryKey: ['repositories'],
    queryFn: fetchRepositories,
  })
}

async function fetchRepository(id: string): Promise<CodeRepository> {
  const { data } = await apiClient.get<CodeRepository>(
    `/api/v1/repositories/${id}`,
  )
  return data
}

export function useRepository(id: string) {
  return useQuery({
    queryKey: ['repositories', id],
    queryFn: () => fetchRepository(id),
    enabled: Boolean(id),
  })
}

async function registerRepository(
  input: RegisterRepositoryInput,
): Promise<CodeRepository> {
  const { data } = await apiClient.post<CodeRepository>(
    '/api/v1/repositories',
    input,
  )
  return data
}

export function useRegisterRepository() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: registerRepository,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repositories'] })
    },
  })
}

async function deleteRepository(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/repositories/${id}`)
}

export function useDeleteRepository() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteRepository,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repositories'] })
    },
  })
}
