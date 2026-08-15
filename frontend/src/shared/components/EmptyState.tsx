import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description: string
  action?: ReactNode
}

// Generic, token-styled empty-state panel (Req: First-Run Onboarding).
// Purely presentational — callers decide the copy and optional action, so
// the same component serves repositories/targets/findings without coupling
// this file to any feature's data shape.
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-border bg-card/50 px-6 py-10 text-center">
      <p className="text-sm font-medium text-foreground">{title}</p>
      <p className="text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}
