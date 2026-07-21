import { FindingsTable } from '@/features/findings/components/FindingsTable'
import { useRepoDiff } from '../queries'

// Self-contained (unlike `TrendsChart`, which is a pure presentational
// component driven by its page): handles its own loading/error/empty states
// so `RepositoryDetailPage` only needs to mount `<DiffPanel repositoryId={id} />`.
export function DiffPanel({ repositoryId }: { repositoryId: string }) {
  const diffQuery = useRepoDiff(repositoryId)

  if (diffQuery.isPending) {
    return <p className="text-muted-foreground">Loading scan diff…</p>
  }

  if (diffQuery.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load the scan diff.
      </p>
    )
  }

  const diff = diffQuery.data

  // Insufficient scan history (design D4/D5): a null baseline means fewer
  // than 2 completed runs exist. Per spec's "Panel handles no baseline"
  // scenario this is always a friendly empty-state, never an error — even
  // though `added` may already contain findings from the sole completed run.
  if (diff.baseline_run == null) {
    return (
      <p className="text-sm text-muted-foreground">
        Not enough scan history yet — the diff will populate after a second
        completed scan run.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold">Added</h4>
        <FindingsTable findings={diff.added} />
      </div>
      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold">Resolved</h4>
        <FindingsTable findings={diff.resolved} />
      </div>
      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold">Carried</h4>
        <FindingsTable findings={diff.carried} />
      </div>
    </div>
  )
}
