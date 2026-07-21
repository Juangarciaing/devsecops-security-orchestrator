import { Badge } from '@/shared/ui/badge'
import { useRepoPolicyCheck } from '../queries'

// Self-contained (mirrors `DiffPanel`): handles its own loading/error/empty
// states so `RepositoryDetailPage` only needs to mount
// `<PolicyGateBadge repositoryId={id} />`. Genuinely the simplest of the
// three 12-series frontend additions — a hook + a small badge, no chart or
// multi-section panel.
export function PolicyGateBadge({ repositoryId }: { repositoryId: string }) {
  const policyQuery = useRepoPolicyCheck(repositoryId)

  if (policyQuery.isPending) {
    return (
      <span className="text-sm text-muted-foreground">
        Loading policy check…
      </span>
    )
  }

  if (policyQuery.isError) {
    return (
      <span role="alert" className="text-sm text-destructive">
        Could not load policy check.
      </span>
    )
  }

  const { verdict } = policyQuery.data

  return (
    <Badge variant={verdict === 'fail' ? 'destructive' : 'default'}>
      {verdict === 'fail' ? 'Fail' : 'Pass'}
    </Badge>
  )
}
