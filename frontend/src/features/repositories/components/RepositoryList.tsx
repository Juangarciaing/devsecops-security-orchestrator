import { EmptyState } from '@/shared/components/EmptyState'
import type { CodeRepository } from '../types'
import { RepositoryCard } from './RepositoryCard'

export function RepositoryList({
  repositories,
}: {
  repositories: CodeRepository[]
}) {
  if (repositories.length === 0) {
    return (
      <EmptyState
        title="No repositories registered yet"
        description="Register one to get started."
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {repositories.map((repository) => (
        <RepositoryCard key={repository.id} repository={repository} />
      ))}
    </div>
  )
}
