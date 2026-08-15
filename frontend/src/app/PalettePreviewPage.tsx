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
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {swatches.map((swatch) => (
          <div
            key={swatch.name}
            className={`flex h-24 flex-col justify-between rounded-lg p-3 ${swatch.className}`}
          >
            <span className="font-mono text-xs">{swatch.name}</span>
            <span className="text-xs opacity-80">{swatch.usedBy}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

export function PalettePreviewPage() {
  return (
    <div className="min-h-screen space-y-8 bg-background p-8 text-foreground">
      <div>
        <h1 className="text-2xl font-bold">New design token preview</h1>
        <p className="text-muted-foreground">
          Dev-only route — verify every swatch label reads with AA contrast
          before approving PR1.
        </p>
      </div>
      <SwatchGrid title="Severity tokens" swatches={SEVERITY_SWATCHES} />
      <SwatchGrid title="Status tokens" swatches={STATUS_SWATCHES} />
      <SwatchGrid title="Sidebar tokens (PR2)" swatches={SIDEBAR_SWATCHES} />
    </div>
  )
}
