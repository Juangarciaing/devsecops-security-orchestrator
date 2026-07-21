import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { TrendPoint } from '../types'
import { TrendsChart } from './TrendsChart'

// jsdom has no real layout engine: recharts' `ResponsiveContainer` measures
// its parent via `ResizeObserver` + `getBoundingClientRect`, both of which
// report 0x0 by default in jsdom, causing the chart to bail out and render
// nothing. Stubbing both to a realistic non-zero size is the standard
// recharts+jsdom testing workaround (recharts itself documents this gap).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      width: 600,
      height: 300,
      top: 0,
      left: 0,
      bottom: 300,
      right: 600,
      x: 0,
      y: 0,
      toJSON() {
        return {}
      },
    }),
  })
})

const points: TrendPoint[] = [
  {
    scan_run_id: 's1',
    occurred_at: '2026-01-01T00:00:00Z',
    commit_sha: 'abc1234',
    introduced: { high: 2, low: 1 },
  },
  {
    scan_run_id: 's2',
    occurred_at: '2026-01-02T00:00:00Z',
    commit_sha: 'def5678',
    introduced: {},
  },
]

describe('TrendsChart', () => {
  it('renders a chart with a legend entry per severity after scans exist', () => {
    render(<TrendsChart points={points} />)

    expect(
      screen.getByRole('img', { name: /findings introduced/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Low')).toBeInTheDocument()
  })

  it('shows an empty state when there are no completed scans', () => {
    render(<TrendsChart points={[]} />)

    expect(screen.getByText(/no completed scans/i)).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
