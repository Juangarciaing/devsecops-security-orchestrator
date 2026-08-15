import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScanRunStatus } from '../types'
import { STATUS_TOKEN_CLASSNAME, ScanStatusBadge } from './ScanStatusBadge'

const STATUS_CASES: [ScanRunStatus, string][] = [
  ['pending', 'Pending'],
  ['running', 'Running'],
  ['completed', 'Completed'],
  ['failed', 'Failed'],
  ['cancelled', 'Cancelled'],
]

describe('ScanStatusBadge', () => {
  it.each(STATUS_CASES)(
    'renders a human-readable label for status %s',
    (status, label) => {
      render(<ScanStatusBadge status={status} />)
      expect(screen.getByText(label)).toBeInTheDocument()
    },
  )

  it.each(STATUS_CASES)(
    'pins the data-status attribute to %s so existing consumers keep working unchanged',
    (status, label) => {
      render(<ScanStatusBadge status={status} />)
      expect(screen.getByText(label)).toHaveAttribute('data-status', status)
    },
  )

  it('renders failed status on the neutral outline base variant now that color comes from the token class map', () => {
    render(<ScanStatusBadge status="failed" />)
    expect(screen.getByText('Failed')).toHaveAttribute(
      'data-variant',
      'outline',
    )
  })

  it('maps every status to a distinct design-system color token class', () => {
    const classNames = Object.values(STATUS_TOKEN_CLASSNAME)
    expect(classNames).toHaveLength(5)
    expect(new Set(classNames).size).toBe(5)
  })
})
