import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScanRunStatus } from '../types'
import { ScanStatusBadge } from './ScanStatusBadge'

describe('ScanStatusBadge', () => {
  it.each([
    ['pending', 'Pending'],
    ['running', 'Running'],
    ['completed', 'Completed'],
    ['failed', 'Failed'],
    ['cancelled', 'Cancelled'],
  ] as [ScanRunStatus, string][])(
    'renders a human-readable label for status %s',
    (status, label) => {
      render(<ScanStatusBadge status={status} />)
      expect(screen.getByText(label)).toBeInTheDocument()
    },
  )

  it('marks a failed scan as destructive-styled', () => {
    render(<ScanStatusBadge status="failed" />)
    expect(screen.getByText('Failed')).toHaveAttribute(
      'data-variant',
      'destructive',
    )
  })
})
