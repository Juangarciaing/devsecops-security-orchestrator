import { describe, expect, it } from 'vitest'
import { toChartRows } from './chartData'
import type { TrendPoint } from './types'

describe('toChartRows', () => {
  it('flattens each point into a dense row with every severity defaulted to 0', () => {
    const points: TrendPoint[] = [
      {
        scan_run_id: 's1',
        occurred_at: '2026-01-01T00:00:00Z',
        commit_sha: 'abc1234',
        introduced: { high: 2 },
      },
    ]

    expect(toChartRows(points)).toEqual([
      {
        scan_run_id: 's1',
        label: 'abc1234',
        occurred_at: '2026-01-01T00:00:00Z',
        critical: 0,
        high: 2,
        medium: 0,
        low: 0,
        info: 0,
      },
    ])
  })

  it('returns an empty array for an empty points list', () => {
    expect(toChartRows([])).toEqual([])
  })

  it('preserves chronological order across multiple points', () => {
    const points: TrendPoint[] = [
      {
        scan_run_id: 's1',
        occurred_at: '2026-01-01T00:00:00Z',
        commit_sha: 'aaa1111',
        introduced: {},
      },
      {
        scan_run_id: 's2',
        occurred_at: '2026-01-02T00:00:00Z',
        commit_sha: 'bbb2222',
        introduced: { critical: 1, low: 3 },
      },
    ]

    const rows = toChartRows(points)
    expect(rows.map((row) => row.scan_run_id)).toEqual(['s1', 's2'])
    expect(rows[1]).toMatchObject({ critical: 1, low: 3 })
  })
})
