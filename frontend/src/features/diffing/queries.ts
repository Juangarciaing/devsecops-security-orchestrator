import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { RepositoryDiff } from './types'

async function fetchRepoDiff(repositoryId: string): Promise<RepositoryDiff> {
  const { data } = await apiClient.get<RepositoryDiff>(
    `/api/v1/repositories/${repositoryId}/diff`,
  )
  return data
}

// Mirrors `useRepoTrends`: disabled until an id is available (e.g. while
// `useParams` hasn't resolved yet).
export function useRepoDiff(repositoryId: string) {
  return useQuery({
    queryKey: ['repositories', repositoryId, 'diff'],
    queryFn: () => fetchRepoDiff(repositoryId),
    enabled: Boolean(repositoryId),
  })
}
