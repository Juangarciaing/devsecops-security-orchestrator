import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { CodeRepository } from '../types'
import { RepositoryCard } from './RepositoryCard'

const repo: CodeRepository = {
  id: 'r1',
  provider: 'github',
  owner: 'acme',
  name: 'widgets',
  clone_url: 'https://github.com/acme/widgets.git',
  default_branch: 'main',
  credential_ref: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderCard() {
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
  return render(<RepositoryCard repository={repo} />, { wrapper: Wrapper })
}

describe('RepositoryCard', () => {
  it('shows the repository identity and a link to its detail page', () => {
    renderCard()

    expect(screen.getByText('acme/widgets')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /acme\/widgets/i }),
    ).toHaveAttribute('href', '/repositories/r1')
  })

  it('offers a trigger-scan action', () => {
    renderCard()

    expect(
      screen.getByRole('button', { name: /trigger scan/i }),
    ).toBeInTheDocument()
  })
})
