import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatTile } from './StatTile'

describe('StatTile', () => {
  it('renders the label and value', () => {
    render(<StatTile label="Total repos" value={24} />)

    expect(screen.getByText('Total repos')).toBeInTheDocument()
    expect(screen.getByText('24')).toBeInTheDocument()
  })

  it('applies the warning tone to the value', () => {
    render(<StatTile label="Critical, open" value={3} tone="warning" />)

    expect(screen.getByText('3')).toHaveClass('text-severity-critical')
  })
})
