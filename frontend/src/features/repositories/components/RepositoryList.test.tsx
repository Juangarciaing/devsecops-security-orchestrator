import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { CodeRepository } from '../types'
import { RepositoryList } from './RepositoryList'

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

function renderList(repositories: CodeRepository[]) {
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
  return render(<RepositoryList repositories={repositories} />, {
    wrapper: Wrapper,
  })
}

describe('RepositoryList', () => {
  it('renders a card per repository', () => {
    renderList([repo, { ...repo, id: 'r2', name: 'gadgets' }])

    expect(screen.getByText('acme/widgets')).toBeInTheDocument()
    expect(screen.getByText('acme/gadgets')).toBeInTheDocument()
  })

  it('shows an empty-state message with a register action when there are none', () => {
    renderList([])

    expect(screen.getByText(/no repositories/i)).toBeInTheDocument()
  })
})
