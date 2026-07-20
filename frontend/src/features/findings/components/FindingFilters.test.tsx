import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { FindingFilters as FindingFiltersValue } from '../types'
import { FindingFilters } from './FindingFilters'

describe('FindingFilters', () => {
  it('calls onChange with the selected severity', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    await user.selectOptions(screen.getByLabelText(/severity/i), 'high')

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'high' }),
    )
  })

  it('calls onChange with the selected status', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<FindingFilters filters={{}} onChange={onChange} />)

    await user.selectOptions(screen.getByLabelText(/status/i), 'suppressed')

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

  it('clears a filter back to "All" (undefined)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const filters: FindingFiltersValue = { severity: 'high' }
    render(<FindingFilters filters={filters} onChange={onChange} />)

    await user.selectOptions(screen.getByLabelText(/severity/i), '')

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ severity: undefined }),
    )
  })
})
