import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders the given title and description', () => {
    render(
      <EmptyState
        title="No targets yet"
        description="Register a scan target to begin."
      />,
    )

    expect(screen.getByText('No targets yet')).toBeInTheDocument()
    expect(
      screen.getByText('Register a scan target to begin.'),
    ).toBeInTheDocument()
  })

  it('renders the optional action when one is provided', () => {
    render(
      <EmptyState
        title="No findings yet"
        description="Findings will appear here once a scan completes."
        action={<button type="button">Trigger scan</button>}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Trigger scan' }),
    ).toBeInTheDocument()
  })

  it('omits the action region when none is provided', () => {
    render(
      <EmptyState
        title="No repositories yet"
        description="Register one to get started."
      />,
    )

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
