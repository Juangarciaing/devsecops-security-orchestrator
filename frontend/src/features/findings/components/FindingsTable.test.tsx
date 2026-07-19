import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { Finding } from '../types'
import { FindingsTable } from './FindingsTable'

function renderTable(findings: Finding[]) {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <FindingsTable findings={findings} />
    </QueryClientProvider>,
  )
}

const fullFinding: Finding = {
  id: 'f1',
  scan_task_id: 't1',
  severity: 'critical',
  status: 'open',
  rule_id: 'generic-api-key',
  title: 'Hardcoded API key',
  fingerprint: 'abc123',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  description: 'A secret was committed',
  file_path: 'src/config.ts',
  line_number: 12,
  raw_evidence: { secret: 'sk-***', match: 'sk-***', commit: 'abc123' },
  snippet: 'const key = "sk-***"',
  repository_id: 'r1',
  first_seen_scan_run_id: 's1',
  last_seen_scan_run_id: 's1',
}

// Member-role redaction nulls these four fields server-side (Req:
// Redaction-Safe Rendering) — the table must render safely without them.
const redactedFinding: Finding = {
  ...fullFinding,
  id: 'f2',
  title: 'Redacted secret',
  file_path: null,
  line_number: null,
  raw_evidence: null,
  snippet: null,
}

describe('FindingsTable', () => {
  it('shows an empty state when there are no findings', () => {
    renderTable([])
    expect(screen.getByText(/no findings/i)).toBeInTheDocument()
  })

  it('renders title, severity, status, rule_id, and file path when present', () => {
    renderTable([fullFinding])

    expect(
      screen.getByRole('columnheader', { name: /rule id/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('Hardcoded API key')).toBeInTheDocument()
    expect(screen.getByText('generic-api-key')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/src\/config\.ts/)).toBeInTheDocument()
  })

  it('renders a redacted finding without file_path/snippet and does not throw', () => {
    expect(() => renderTable([redactedFinding])).not.toThrow()

    expect(screen.getByText('Redacted secret')).toBeInTheDocument()
    // rule_id is not redaction-sensitive — still renders for member.
    expect(screen.getByText('generic-api-key')).toBeInTheDocument()
    expect(screen.queryByText(/src\/config\.ts/)).not.toBeInTheDocument()
  })

  it('does not offer a details toggle when snippet/raw_evidence are absent (redacted)', () => {
    renderTable([redactedFinding])

    expect(
      screen.queryByRole('button', { name: /details/i }),
    ).not.toBeInTheDocument()
  })

  it('reveals snippet and raw evidence for admin after clicking Details, without leaking them by default', async () => {
    const user = userEvent.setup()
    renderTable([fullFinding])

    // Not shown until expanded.
    expect(
      screen.queryByText(fullFinding.snippet as string),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByText(fullFinding.snippet as string)).toBeInTheDocument()
    expect(screen.getByText(/"match"/)).toBeInTheDocument()
    expect(screen.getByText(/"commit"/)).toBeInTheDocument()
  })
})
