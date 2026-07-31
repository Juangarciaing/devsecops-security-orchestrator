import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { ScanTarget } from '../types'
import { TargetList } from './TargetList'

const target: ScanTarget = {
  id: 't1',
  name: 'staging web app',
  target_url: 'https://staging.example.com',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderList(targets: ScanTarget[]) {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>{children}</AuthProvider>
        </QueryClientProvider>
      </MemoryRouter>
    )
  }
  return render(<TargetList targets={targets} />, { wrapper: Wrapper })
}

describe('TargetList', () => {
  it('renders a card per target', () => {
    renderList([target, { ...target, id: 't2', name: 'prod web app' }])

    expect(screen.getByText('staging web app')).toBeInTheDocument()
    expect(screen.getByText('prod web app')).toBeInTheDocument()
  })

  it('shows an empty-state message when there are none', () => {
    renderList([])

    expect(screen.getByText(/no scan targets/i)).toBeInTheDocument()
  })
})
