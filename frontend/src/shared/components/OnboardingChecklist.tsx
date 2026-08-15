export type OnboardingStage =
  | 'zero-repositories'
  | 'zero-scans'
  | 'zero-findings'
  | 'complete'

interface OnboardingStatus {
  hasRepository: boolean
  hasCompletedScan: boolean
  hasFinding: boolean
}

// Pure stage resolver (Req: First-Run Onboarding) — no branching lives in
// the component so the three onboarding states stay independently testable
// without rendering React.
export function resolveOnboardingStage({
  hasRepository,
  hasCompletedScan,
  hasFinding,
}: OnboardingStatus): OnboardingStage {
  if (!hasRepository) return 'zero-repositories'
  if (!hasCompletedScan) return 'zero-scans'
  if (!hasFinding) return 'zero-findings'
  return 'complete'
}

const STEP_LABELS = [
  'Register a repository',
  'Run a scan',
  'Review findings',
] as const

const STAGE_COPY: Record<
  Exclude<OnboardingStage, 'complete'>,
  { title: string; description: string }
> = {
  'zero-repositories': {
    title: 'Register your first repository',
    description:
      'Connect a repository so scans have something to check for security issues.',
  },
  'zero-scans': {
    title: 'Run your first scan',
    description:
      'You have a registered repository — trigger a scan to look for findings.',
  },
  'zero-findings': {
    title: 'No findings yet',
    description:
      'Your latest scan completed and found no issues so far. Nice work.',
  },
}

// Stage-aware next-action prompt (Req: First-Run Onboarding, design D6) —
// mounted inside RepositoriesPage, never as a standalone dashboard route.
export function OnboardingChecklist(props: OnboardingStatus) {
  const stage = resolveOnboardingStage(props)
  if (stage === 'complete') {
    return null
  }

  const copy = STAGE_COPY[stage]
  const completedSteps = [
    props.hasRepository,
    props.hasCompletedScan,
    props.hasFinding,
  ]

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-sm font-medium text-foreground">{copy.title}</p>
      <p className="text-sm text-muted-foreground">{copy.description}</p>
      <ol className="mt-3 flex flex-col gap-1 text-sm">
        {STEP_LABELS.map((label, index) => (
          <li
            key={label}
            className={
              completedSteps[index]
                ? 'text-muted-foreground line-through'
                : 'text-foreground'
            }
          >
            {index + 1}. {label}
          </li>
        ))}
      </ol>
    </div>
  )
}
