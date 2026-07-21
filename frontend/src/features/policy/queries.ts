import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/shared/api/client'
import type { RepositoryPolicy } from './types'

async function fetchRepoPolicyCheck(
  repositoryId: string,
): Promise<RepositoryPolicy> {
  const { data } = await apiClient.get<RepositoryPolicy>(
    `/api/v1/repositories/${repositoryId}/policy-check`,
  )
  return data
}

// Mirrors `useRepoTrends`/`useRepoDiff`: disabled until an id is available
// (e.g. while `useParams` hasn't resolved yet).
export function useRepoPolicyCheck(repositoryId: string) {
  return useQuery({
    queryKey: ['repositories', repositoryId, 'policy-check'],
    queryFn: () => fetchRepoPolicyCheck(repositoryId),
    enabled: Boolean(repositoryId),
  })
}
