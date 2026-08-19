import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
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
  it('shows a table skeleton while findings are loading', async () => {
    server.use(
      http.get('*/api/v1/findings', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when findings fail to load', async () => {
    server.use(
      http.get('*/api/v1/findings', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

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

    const severityGroup = screen.getByRole('group', {
      name: /filter by severity/i,
    })
    await user.click(
      within(severityGroup).getByRole('button', { name: 'Critical' }),
    )

    await waitFor(() => expect(seenOffsets[seenOffsets.length - 1]).toBe('0'))
  })

  it('advances the offset via the Next button using real server-side pagination', async () => {
    const user = userEvent.setup()
    const seenOffsets: string[] = []
    server.use(
      http.get('*/api/v1/findings', ({ request }) => {
        const url = new URL(request.url)
        const offset = url.searchParams.get('offset') ?? '0'
        // The page also fires an unfiltered, unpaginated `useFindings({})`
        // for the stat strip — only the real paginated request carries
        // `limit`, so that's the one this test tracks.
        if (url.searchParams.has('limit')) {
          seenOffsets.push(offset)
        }
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

  it('derives the stat strip from the unfiltered findings list', async () => {
    server.use(
      http.get('*/api/v1/findings', () =>
        HttpResponse.json([
          makeFinding('f1', { severity: 'critical', status: 'open' }),
          makeFinding('f2', { severity: 'high', status: 'open' }),
          makeFinding('f3', { severity: 'high', status: 'suppressed' }),
        ]),
      ),
    )
    renderPage()

    await screen.findByText('Finding f1')

    function tileValue(label: string) {
      const tile = screen.getByText(label).closest('[data-slot="stat-tile"]')
      return within(tile as HTMLElement).getByText(/^\d+$/).textContent
    }

    expect(tileValue('Total findings')).toBe('3')
    expect(tileValue('Critical, open')).toBe('1')
    expect(tileValue('High, open')).toBe('1')
    expect(tileValue('Suppressed findings')).toBe('1')
  })
})
