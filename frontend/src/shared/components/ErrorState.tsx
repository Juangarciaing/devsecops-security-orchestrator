import { Button } from '@/shared/ui/button'

interface ErrorStateProps {
  title?: string
  description: string
  onRetry?: () => void
}

// Generic, token-styled error-state panel (Req: State Coverage). Mirrors
// EmptyState's shape — presentational, no data coupling — but signals a
// failure via role="alert" and a single uniform Retry affordance, since
// every caller has a TanStack Query `refetch` to hand it.
export function ErrorState({
  title = 'Something went wrong',
  description,
  onRetry,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="animate-row-in flex flex-col items-center gap-1 rounded-lg border border-dashed border-destructive/30 bg-surface-sunken px-6 py-10 text-center"
    >
      <p className="text-heading text-foreground">{title}</p>
      <p className="text-body text-muted-foreground">{description}</p>
      {onRetry ? (
        <div className="mt-3">
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  )
}
