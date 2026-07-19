import { Link } from 'react-router'
import { Badge } from '@/shared/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { TriggerScanButton } from '@/features/scans/components/TriggerScanButton'
import type { CodeRepository } from '../types'
import { DeleteRepositoryButton } from './DeleteRepositoryButton'

export function RepositoryCard({ repository }: { repository: CodeRepository }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>
          <Link
            to={`/repositories/${repository.id}`}
            className="hover:underline"
          >
            {repository.owner}/{repository.name}
          </Link>
        </CardTitle>
        <Badge variant="outline">{repository.provider}</Badge>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <span className="text-sm text-muted-foreground">
          Default branch: {repository.default_branch}
        </span>
        <div className="flex items-center gap-2">
          <TriggerScanButton repositoryId={repository.id} />
          <DeleteRepositoryButton repositoryId={repository.id} />
        </div>
      </CardContent>
    </Card>
  )
}
