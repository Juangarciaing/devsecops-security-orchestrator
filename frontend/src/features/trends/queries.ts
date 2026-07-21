import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { RepositoryTrends } from './types'

async function fetchRepoTrends(
  repositoryId: string,
): Promise<RepositoryTrends> {
  const { data } = await apiClient.get<RepositoryTrends>(
    `/api/v1/repositories/${repositoryId}/trends`,
  )
  return data
}

// Mirrors `useRepositoryScans`/`useRepository`: disabled until an id is
// available (e.g. while `useParams` hasn't resolved yet).
export function useRepoTrends(repositoryId: string) {
  return useQuery({
    queryKey: ['repositories', repositoryId, 'trends'],
    queryFn: () => fetchRepoTrends(repositoryId),
    enabled: Boolean(repositoryId),
  })
}
