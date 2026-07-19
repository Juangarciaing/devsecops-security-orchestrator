import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { ScanRun } from '../types'
import { ScanHistoryTable } from './ScanHistoryTable'

const scan: ScanRun = {
  id: 's1',
  repository_id: 'r1',
  status: 'completed',
  trigger: 'manual',
  commit_sha: 'main',
  ref: 'main',
  created_at: '2026-01-01T00:00:00Z',
  started_at: '2026-01-01T00:00:01Z',
  completed_at: '2026-01-01T00:00:10Z',
}

function renderTable(scans: ScanRun[]) {
  return render(
    <MemoryRouter>
      <ScanHistoryTable scans={scans} />
    </MemoryRouter>,
  )
}

describe('ScanHistoryTable', () => {
  it('lists each scan with status and a link to its detail page', () => {
    renderTable([scan])

    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('main')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view/i })).toHaveAttribute(
      'href',
      '/scans/s1',
    )
  })

  it('shows an empty state when there are no prior scans', () => {
    renderTable([])

    expect(screen.getByText(/no scans/i)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
