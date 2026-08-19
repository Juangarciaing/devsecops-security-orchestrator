import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CardGridSkeleton } from './CardGridSkeleton'

describe('CardGridSkeleton', () => {
  it('renders the default card count (3)', () => {
    const { container } = render(<CardGridSkeleton />)

    expect(container.querySelectorAll('[data-slot="card"]')).toHaveLength(3)
  })

  it('renders a custom card count when provided', () => {
    const { container } = render(<CardGridSkeleton count={5} />)

    expect(container.querySelectorAll('[data-slot="card"]')).toHaveLength(5)
  })

  it('renders the Skeleton primitive inside every card, not a reimplementation', () => {
    const { container } = render(<CardGridSkeleton count={2} />)

    expect(container.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(4)
  })
})
