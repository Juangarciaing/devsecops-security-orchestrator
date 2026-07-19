import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
  raw_evidence: { match: 'sk-***' },
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

  it('renders title, severity, status, and file path when present', () => {
    renderTable([fullFinding])

    expect(screen.getByText('Hardcoded API key')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/src\/config\.ts/)).toBeInTheDocument()
  })

  it('renders a redacted finding without file_path/snippet and does not throw', () => {
    expect(() => renderTable([redactedFinding])).not.toThrow()

    expect(screen.getByText('Redacted secret')).toBeInTheDocument()
    expect(screen.queryByText(/src\/config\.ts/)).not.toBeInTheDocument()
  })
})
