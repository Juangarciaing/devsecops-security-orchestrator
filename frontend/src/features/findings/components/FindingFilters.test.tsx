import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { FindingFilters as FindingFiltersValue } from '../types'
import { FindingFilters } from './FindingFilters'

describe('FindingFilters', () => {
  it('calls onChange with the selected severity', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    const severityGroup = screen.getByRole('group', {
      name: /filter by severity/i,
    })
    await user.click(within(severityGroup).getByRole('button', { name: 'High' }))

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'high' }),
    )
  })

  it('calls onChange with the selected status', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    const statusGroup = screen.getByRole('group', {
      name: /filter by status/i,
    })
    await user.click(
      within(statusGroup).getByRole('button', { name: 'Suppressed' }),
    )

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'suppressed' }),
    )
  })

  it('calls onChange with the selected scanner type', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    await user.selectOptions(screen.getByLabelText(/scanner/i), 'secrets')

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ scanner_type: 'secrets' }),
    )
  })

  it('offers semgrep as a selectable scanner type', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    await user.selectOptions(screen.getByLabelText(/scanner/i), 'semgrep')

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ scanner_type: 'semgrep' }),
    )
  })

  it('clears the severity filter back to "All" (undefined)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const filters: FindingFiltersValue = { severity: 'high' }
    render(<FindingFilters filters={filters} onChange={onChange} />)

    const severityGroup = screen.getByRole('group', {
      name: /filter by severity/i,
    })
    await user.click(within(severityGroup).getByRole('button', { name: 'All' }))

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ severity: undefined }),
    )
  })

  it('marks the active severity chip as pressed', () => {
    render(<FindingFilters filters={{ severity: 'critical' }} onChange={() => {}} />)

    const severityGroup = screen.getByRole('group', {
      name: /filter by severity/i,
    })
    expect(
      within(severityGroup).getByRole('button', { name: 'Critical' }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      within(severityGroup).getByRole('button', { name: 'All' }),
    ).toHaveAttribute('aria-pressed', 'false')
  })
})
