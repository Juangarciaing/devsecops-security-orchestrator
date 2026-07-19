import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { FindingsPage } from './FindingsPage'

function makeFinding(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    scan_task_id: 't1',
    severity: 'high',
    status: 'open',
    rule_id: 'generic-api-key',
    title: `Finding ${id}`,
    fingerprint: `fp-${id}`,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    description: null,
    file_path: null,
    line_number: null,
    raw_evidence: null,
    snippet: null,
    repository_id: 'r1',
    first_seen_scan_run_id: 's1',
    last_seen_scan_run_id: 's1',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <FindingsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('FindingsPage', () => {
  it('renders the fetched findings', async () => {
    server.use(
      http.get('*/api/v1/findings', () =>
        HttpResponse.json([makeFinding('f1')]),
      ),
    )
    renderPage()

    expect(await screen.findByText('Finding f1')).toBeInTheDocument()
  })

  it('resets to the first page when a filter changes', async () => {
    const user = userEvent.setup()
    const seenOffsets: string[] = []
    server.use(
      http.get('*/api/v1/findings', ({ request }) => {
        const url = new URL(request.url)
        seenOffsets.push(url.searchParams.get('offset') ?? '')
        return HttpResponse.json(
          Array.from({ length: 20 }, (_, i) => makeFinding(`page1-${i}`)),
        )
      }),
    )
    renderPage()

    await screen.findByText('Finding page1-0')
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(seenOffsets).toContain('20'))

    await user.selectOptions(screen.getByLabelText(/severity/i), 'critical')

    await waitFor(() => expect(seenOffsets[seenOffsets.length - 1]).toBe('0'))
  })

  it('advances the offset via the Next button using real server-side pagination', async () => {
    const user = userEvent.setup()
    const seenOffsets: string[] = []
    server.use(
      http.get('*/api/v1/findings', ({ request }) => {
        const url = new URL(request.url)
        const offset = url.searchParams.get('offset') ?? '0'
        seenOffsets.push(offset)
        return HttpResponse.json(
          Array.from({ length: 20 }, (_, i) => makeFinding(`p${offset}-${i}`)),
        )
      }),
    )
    renderPage()

    await screen.findByText('Finding p0-0')
    await user.click(screen.getByRole('button', { name: /next/i }))

    expect(await screen.findByText('Finding p20-0')).toBeInTheDocument()
    expect(seenOffsets).toEqual(['0', '20'])
  })
})
