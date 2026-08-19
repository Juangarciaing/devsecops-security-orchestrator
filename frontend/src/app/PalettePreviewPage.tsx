// Dev-only design-token swatch preview. Not linked from any nav — reachable
// only at `/dev/palette-preview`, and the route itself only exists when
// Vite's `import.meta.env.DEV` is true (see router.tsx), so it never ships
// in a production build.
//
// Purpose: give a human a single screen to eyeball every token this change
// newly introduces and manually confirm AA contrast (task 1.7 pre-flight
// gate) before PR1 is approved. Pre-existing tokens (background, primary,
// etc.) only changed value, not name, so they are out of scope here.

type Swatch = { name: string; className: string; usedBy: string }

const SEVERITY_SWATCHES: Swatch[] = [
  {
    name: '--severity-critical',
    className: 'bg-severity-critical text-severity-critical-foreground',
    usedBy: 'SeverityBadge: critical',
  },
  {
    name: '--severity-high',
    className: 'bg-severity-high text-severity-high-foreground',
    usedBy: 'SeverityBadge: high',
  },
  {
    name: '--severity-medium',
    className: 'bg-severity-medium text-severity-medium-foreground',
    usedBy: 'SeverityBadge: medium',
  },
  {
    name: '--severity-low',
    className: 'bg-severity-low text-severity-low-foreground',
    usedBy: 'SeverityBadge: low',
  },
  {
    name: '--severity-info',
    className: 'bg-severity-info text-severity-info-foreground',
    usedBy: 'SeverityBadge: info',
  },
]

const STATUS_SWATCHES: Swatch[] = [
  {
    name: '--status-pending',
    className: 'border border-status-pending text-status-pending bg-card',
    usedBy: 'ScanStatusBadge: pending',
  },
  {
    name: '--status-running',
    className: 'border border-status-running text-status-running bg-card',
    usedBy: 'ScanStatusBadge: running',
  },
  {
    name: '--status-completed',
    className: 'border border-status-completed text-status-completed bg-card',
    usedBy: 'ScanStatusBadge: completed',
  },
  {
    name: '--status-failed',
    className: 'border border-status-failed text-status-failed bg-card',
    usedBy: 'ScanStatusBadge: failed',
  },
  {
    name: '--status-cancelled',
    className: 'border border-status-cancelled text-status-cancelled bg-card',
    usedBy: 'ScanStatusBadge: cancelled',
  },
]

const SIDEBAR_SWATCHES: Swatch[] = [
  {
    name: '--sidebar / --sidebar-foreground',
    className:
      'bg-sidebar text-sidebar-foreground border border-sidebar-border',
    usedBy: 'AppSidebar shell (PR2)',
  },
  {
    name: '--sidebar-primary / --sidebar-primary-foreground',
    className: 'bg-sidebar-primary text-sidebar-primary-foreground',
    usedBy: 'AppSidebar active item (PR2)',
  },
  {
    name: '--sidebar-accent / --sidebar-accent-foreground',
    className: 'bg-sidebar-accent text-sidebar-accent-foreground',
    usedBy: 'AppSidebar hover state (PR2)',
  },
]

function SwatchGrid({ title, swatches }: { title: string; swatches: Swatch[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-heading">{title}</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {swatches.map((swatch) => (
          <div
            key={swatch.name}
            className={`flex h-24 flex-col justify-between rounded-lg p-3 ${swatch.className}`}
          >
            <span className="font-mono text-meta">{swatch.name}</span>
            <span className="text-meta opacity-80">{swatch.usedBy}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

type TypeScaleStep = { name: string; className: string; sample: string }

const TYPE_SCALE_STEPS: TypeScaleStep[] = [
  { name: 'text-display', className: 'text-display', sample: 'Display — Aa Bb Cc 0123' },
  { name: 'text-heading', className: 'text-heading', sample: 'Heading — Aa Bb Cc 0123' },
  {
    name: 'text-subheading',
    className: 'text-subheading',
    sample: 'Subheading — Aa Bb Cc 0123',
  },
  { name: 'text-body', className: 'text-body', sample: 'Body — Aa Bb Cc 0123' },
  { name: 'text-label', className: 'text-label', sample: 'Label — Aa Bb Cc 0123' },
  { name: 'text-meta', className: 'text-meta', sample: 'Meta — Aa Bb Cc 0123' },
  {
    name: 'text-code',
    className: 'text-code font-mono',
    sample: 'Code — Aa Bb Cc 0123',
  },
]

function TypographySection() {
  return (
    <section className="space-y-3">
      <h2 className="text-heading">Typography</h2>
      <div className="space-y-2 rounded-lg border border-border bg-card p-4">
        {TYPE_SCALE_STEPS.map((step) => (
          <div key={step.name} className="flex flex-wrap items-baseline gap-4">
            <span className="w-36 shrink-0 font-mono text-meta text-muted-foreground">
              {step.name}
            </span>
            <p className={step.className}>{step.sample}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

type ElevationBox = { name: string; shadowClassName: string; bgClassName: string }

const ELEVATION_BOXES: ElevationBox[] = [
  { name: 'shadow-e1 / bg-surface-raised', shadowClassName: 'shadow-e1', bgClassName: 'bg-surface-raised' },
  { name: 'shadow-e2 / bg-card', shadowClassName: 'shadow-e2', bgClassName: 'bg-card' },
  { name: 'shadow-e3 / bg-surface-sunken', shadowClassName: 'shadow-e3', bgClassName: 'bg-surface-sunken' },
]

function ElevationSection() {
  return (
    <section className="space-y-3">
      <h2 className="text-heading">Elevation</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {ELEVATION_BOXES.map((box) => (
          <div
            key={box.name}
            className={`flex h-24 flex-col justify-between rounded-lg p-3 ${box.bgClassName} ${box.shadowClassName}`}
          >
            <span className="font-mono text-meta">{box.name}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function MotionSection() {
  return (
    <section className="space-y-3">
      <h2 className="text-heading">Motion</h2>
      <div className="flex flex-wrap items-center gap-6 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-row-in h-16 w-16 rounded-lg bg-primary" />
          <span className="font-mono text-meta text-muted-foreground">
            animate-row-in (plays on mount)
          </span>
        </div>
        <div className="flex flex-col items-center gap-2">
          <div className="animate-status-pulse h-16 w-16 rounded-full bg-status-running" />
          <span className="font-mono text-meta text-muted-foreground">
            animate-status-pulse (loops)
          </span>
        </div>
      </div>
      <p className="text-meta text-muted-foreground">
        Enable your OS-level &quot;reduce motion&quot; setting and reload this
        page — both elements above must stop animating (Req5).
      </p>
    </section>
  )
}

function FontsSection() {
  return (
    <section className="space-y-3">
      <h2 className="text-heading">Fonts</h2>
      <div className="space-y-2 rounded-lg border border-border bg-card p-4">
        <p className="font-sans text-body font-normal">
          font-sans 400 — The quick brown fox jumps over the lazy dog
        </p>
        <p className="font-sans text-body font-medium">
          font-sans 500 — The quick brown fox jumps over the lazy dog
        </p>
        <p className="font-sans text-body font-semibold">
          font-sans 600 — The quick brown fox jumps over the lazy dog
        </p>
        <p className="font-mono text-code font-normal">
          font-mono 400 — const scan = await runScanner(target)
        </p>
        <p className="font-mono text-code font-medium">
          font-mono 500 — const scan = await runScanner(target)
        </p>
      </div>
    </section>
  )
}

export function PalettePreviewPage() {
  return (
    <div className="min-h-screen space-y-8 bg-background p-8 text-foreground">
      <div>
        <h1 className="text-display">New design token preview</h1>
        <p className="text-body text-muted-foreground">
          Dev-only route — verify every swatch label reads with AA contrast
          before approving PR1.
        </p>
      </div>
      <SwatchGrid title="Severity tokens" swatches={SEVERITY_SWATCHES} />
      <SwatchGrid title="Status tokens" swatches={STATUS_SWATCHES} />
      <SwatchGrid title="Sidebar tokens (PR2)" swatches={SIDEBAR_SWATCHES} />
      <TypographySection />
      <ElevationSection />
      <MotionSection />
      <FontsSection />
    </div>
  )
}
