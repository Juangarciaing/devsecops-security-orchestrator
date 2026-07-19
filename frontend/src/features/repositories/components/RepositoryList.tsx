import type { CodeRepository } from '../types'
import { RepositoryCard } from './RepositoryCard'

export function RepositoryList({
  repositories,
}: {
  repositories: CodeRepository[]
}) {
  if (repositories.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No repositories registered yet. Register one to get started.
      </p>
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
