import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { ScanTarget } from '../types'
import { TargetsPage } from './TargetsPage'

function target(id: string): ScanTarget {
  return {
    id,
    name: `target-${id}`,
    target_url: `https://target-${id}.example.com`,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function renderPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TargetsPage />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('TargetsPage', () => {
  it('shows a card-grid skeleton while targets are loading', async () => {
    server.use(
      http.get('*/api/v1/targets', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const { container } = renderPage()

    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0)
  })

  it('shows an error state with a retry action when targets fail to load', async () => {
    server.use(
      http.get('*/api/v1/targets', () => new HttpResponse(null, { status: 500 })),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument()
  })

  it('shows an empty state with a register action when there are no targets', async () => {
    server.use(http.get('*/api/v1/targets', () => HttpResponse.json([])))
    renderPage()

    expect(await screen.findByText(/no scan targets/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /register target/i }),
    ).toBeInTheDocument()
  })

  it('lists registered targets', async () => {
    server.use(
      http.get('*/api/v1/targets', () =>
        HttpResponse.json([target('1'), target('2')]),
      ),
    )
    renderPage()

    expect(await screen.findByText('target-1')).toBeInTheDocument()
    expect(screen.getByText('target-2')).toBeInTheDocument()
  })
})
