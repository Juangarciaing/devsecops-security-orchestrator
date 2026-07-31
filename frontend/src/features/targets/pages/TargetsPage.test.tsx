import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
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
