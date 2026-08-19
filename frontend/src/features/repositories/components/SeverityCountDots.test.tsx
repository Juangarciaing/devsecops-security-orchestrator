import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SeverityCountDots } from './SeverityCountDots'

describe('SeverityCountDots', () => {
  it('renders one dot+count per present severity, most-severe-first', () => {
    const { container } = render(
      <SeverityCountDots counts={{ high: 1, critical: 2 }} />,
    )

    const labels = Array.from(
      container.querySelectorAll('.sr-only'),
    ).map((node) => node.textContent)
    expect(labels).toEqual(['critical', 'high'])
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('omits severities with a zero or absent count', () => {
    render(<SeverityCountDots counts={{ critical: 0, medium: 3 }} />)

    expect(screen.queryByText('critical', { selector: '.sr-only' })).not.toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows a "No open findings" fallback when counts is empty', () => {
    render(<SeverityCountDots counts={{}} />)

    expect(screen.getByText('No open findings')).toBeInTheDocument()
  })
})
