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
  has_credential: false,
  credential_kind: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderCard(repository: CodeRepository = repo) {
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
  return render(<RepositoryCard repository={repository} />, {
    wrapper: Wrapper,
  })
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

  it('shows a credential badge reflecting a configured credential', () => {
    renderCard({
      ...repo,
      has_credential: true,
      credential_kind: 'personal_access_token',
    })

    const badge = screen.getByText(/personal access token/i)
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('data-credential', 'present')
    expect(
      screen.queryByRole('button', { name: /clear credential/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /delete credential/i }),
    ).not.toBeInTheDocument()
  })

  it('shows a "no credential" badge when the repository has none', () => {
    renderCard()

    const badge = screen.getByText(/no credential/i)
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('data-credential', 'absent')
  })
})
