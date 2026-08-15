import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TableSkeleton } from './TableSkeleton'

describe('TableSkeleton', () => {
  it('renders the default row count (5) with the given column count', () => {
    const { container } = render(
      <table>
        <TableSkeleton columns={4} />
      </table>,
    )

    const rows = container.querySelectorAll('[data-slot="table-row"]')
    expect(rows).toHaveLength(5)
    rows.forEach((row) => {
      expect(row.querySelectorAll('[data-slot="table-cell"]')).toHaveLength(4)
    })
  })

  it('renders a custom row count when provided', () => {
    const { container } = render(
      <table>
        <TableSkeleton rows={3} columns={2} />
      </table>,
    )

    expect(container.querySelectorAll('[data-slot="table-row"]')).toHaveLength(3)
  })

  it('renders the Skeleton primitive in every cell, not a reimplementation', () => {
    const { container } = render(
      <table>
        <TableSkeleton rows={2} columns={3} />
      </table>,
    )

    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(6)
  })
})
