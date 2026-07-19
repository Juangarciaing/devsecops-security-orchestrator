import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FindingStatusBadge } from './FindingStatusBadge'

describe('FindingStatusBadge', () => {
  it.each([
    ['open', 'Open'],
    ['resolved', 'Resolved'],
    ['suppressed', 'Suppressed'],
    ['false_positive', 'False positive'],
  ] as const)('renders the %s label', (status, label) => {
    render(<FindingStatusBadge status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('marks a secondary-variant badge for suppressed status', () => {
    render(<FindingStatusBadge status="suppressed" />)
    expect(screen.getByText('Suppressed')).toHaveAttribute(
      'data-variant',
      'secondary',
    )
  })
})
