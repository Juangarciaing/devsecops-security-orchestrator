import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ErrorState } from './ErrorState'

describe('ErrorState', () => {
  it('renders as an alert region', () => {
    render(<ErrorState description="Something failed to load." />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('renders the given description', () => {
    render(<ErrorState description="Unable to fetch repositories." />)

    expect(
      screen.getByText('Unable to fetch repositories.'),
    ).toBeInTheDocument()
  })

  it('renders the default title when none is provided', () => {
    render(<ErrorState description="Unable to fetch repositories." />)

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('renders a custom title when provided', () => {
    render(
      <ErrorState
        title="Failed to load targets"
        description="Unable to fetch targets."
      />,
    )

    expect(screen.getByText('Failed to load targets')).toBeInTheDocument()
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  it('omits the retry action when onRetry is not provided', () => {
    render(<ErrorState description="Unable to fetch repositories." />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('fires onRetry when the Retry button is clicked', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()

    render(
      <ErrorState description="Unable to fetch repositories." onRetry={onRetry} />,
    )

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(onRetry).toHaveBeenCalledOnce()
  })
})
