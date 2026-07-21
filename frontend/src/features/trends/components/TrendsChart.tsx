import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { FindingSeverity } from '@/features/findings/types'
import { SEVERITY_ORDER, toChartRows } from '../chartData'
import type { TrendPoint } from '../types'

const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

// Same palette intent as `SeverityBadge` (critical/high = danger, medium =
// warning, low/info = muted) — recharts needs concrete hex values, not
// Tailwind classes, since fills are drawn on an SVG canvas.
const SEVERITY_COLOR: Record<FindingSeverity, string> = {
  critical: '#dc2626',
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#3b82f6',
  info: '#94a3b8',
}

export function TrendsChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No completed scans yet — the trend chart will populate after the first
        completed scan run.
      </p>
    )
  }

  const rows = toChartRows(points)

  return (
    <div
      role="img"
      aria-label="Findings introduced per scan run, by severity"
      className="h-[300px] w-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Legend />
          {SEVERITY_ORDER.map((severity) => (
            <Bar
              key={severity}
              dataKey={severity}
              name={SEVERITY_LABEL[severity]}
              stackId="introduced"
              fill={SEVERITY_COLOR[severity]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
