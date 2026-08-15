import type { ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Slot } from 'radix-ui'

import { cn } from '@/shared/lib/utils'

interface SeverityStripeProps {
  active: boolean
  className?: string
  children: ReactNode
}

// Presentational severity-stripe primitive (Req7). Wraps a single child —
// a <TableCell> or a <Card> header — via radix-ui's Slot.Root, the same
// asChild convention shared/ui/badge.tsx uses, and merges a left-edge
// stripe onto it. Uses border-left, never an inset box-shadow: Tailwind's
// preflight sets border-collapse: collapse on tables, so a box-shadow
// inset does not paint on table cells. This primitive never derives
// severity itself — callers (Findings, RepositoryDetail) supply `active`
// (e.g. a `hasOpenCritical` boolean) already computed.
export function SeverityStripe({
  active,
  className,
  children,
}: SeverityStripeProps) {
  return (
    <Slot.Root
      data-critical={active ? 'true' : undefined}
      className={cn(active && 'border-l-2 border-l-severity-critical', className)}
    >
      {children}
    </Slot.Root>
  )
}

interface CriticalCueProps {
  active: boolean
}

// Non-color cue paired with SeverityStripe per WCAG 1.4.1 (Req7): an
// aria-hidden icon plus a screen-reader-only label, since color alone
// never carries the "open critical finding" signal.
export function CriticalCue({ active }: CriticalCueProps) {
  if (!active) return null

  return (
    <span className="inline-flex items-center">
      <AlertTriangle aria-hidden="true" className="size-4 text-severity-critical" />
      <span className="sr-only">Open critical finding</span>
    </span>
  )
}
