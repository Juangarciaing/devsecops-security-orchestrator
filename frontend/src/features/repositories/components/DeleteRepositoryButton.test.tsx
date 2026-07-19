import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import { DeleteRepositoryButton } from './DeleteRepositoryButton'

function mockCurrentUser(role: 'admin' | 'member') {
  setToken('a-valid-token')
  server.use(
    http.get('*/api/v1/auth/me', () =>
      HttpResponse.json({
        id: 'u1',
        email: 'a@b.com',
        role,
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
}

function renderButton() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    )
  }
  return render(<DeleteRepositoryButton repositoryId="r1" />, {
    wrapper: Wrapper,
  })
}

describe('DeleteRepositoryButton', () => {
  afterEach(() => {
    clearToken()
  })

  it('is hidden for a member', async () => {
    mockCurrentUser('member')
    renderButton()

    await waitFor(() =>
      expect(screen.queryByRole('button')).not.toBeInTheDocument(),
    )
  })

  it('is visible for an admin and deletes on confirm', async () => {
    mockCurrentUser('admin')
    server.use(
      http.delete(
        '*/api/v1/repositories/r1',
        () => new HttpResponse(null, { status: 204 }),
      ),
    )
    const user = userEvent.setup()
    renderButton()

    const deleteButton = await screen.findByRole('button', {
      name: /delete repository/i,
    })
    await user.click(deleteButton)
    await user.click(await screen.findByRole('button', { name: /confirm/i }))

    await waitFor(() =>
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(),
    )
  })
})
