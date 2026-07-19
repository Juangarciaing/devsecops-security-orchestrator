import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SeverityBadge } from './SeverityBadge'

describe('SeverityBadge', () => {
  it.each([
    ['critical', 'Critical'],
    ['high', 'High'],
    ['medium', 'Medium'],
    ['low', 'Low'],
    ['info', 'Info'],
  ] as const)('renders the %s label', (severity, label) => {
    render(<SeverityBadge severity={severity} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('marks a destructive-variant badge for critical severity', () => {
    render(<SeverityBadge severity="critical" />)
    expect(screen.getByText('Critical')).toHaveAttribute(
      'data-variant',
      'destructive',
    )
  })

  it('marks a secondary-variant badge for info severity', () => {
    render(<SeverityBadge severity="info" />)
    expect(screen.getByText('Info')).toHaveAttribute(
      'data-variant',
      'secondary',
    )
  })
})
