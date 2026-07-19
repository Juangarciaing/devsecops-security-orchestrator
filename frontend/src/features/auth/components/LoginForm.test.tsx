import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { getToken } from '@/shared/api/token'
import { LoginForm } from './LoginForm'

const mockNavigate = vi.fn()
vi.mock('react-router', async () => {
  const actual =
    await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => mockNavigate }
})

function renderLoginForm() {
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
  return render(<LoginForm />, { wrapper: Wrapper })
}

describe('LoginForm', () => {
  afterEach(() => {
    localStorage.clear()
    mockNavigate.mockClear()
  })

  it('stores the token and navigates to / on valid credentials', async () => {
    server.use(
      http.post('*/api/v1/auth/login', () =>
        HttpResponse.json({ access_token: 'good-token', token_type: 'bearer' }),
      ),
    )
    const user = userEvent.setup()
    renderLoginForm()

    await user.type(screen.getByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true }),
    )
    expect(getToken()).toBe('good-token')
  })

  it('shows an error and keeps the user on the page for invalid credentials', async () => {
    server.use(
      http.post(
        '*/api/v1/auth/login',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Unauthorized',
              detail: 'Incorrect email or password.',
            }),
            {
              status: 401,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const user = userEvent.setup()
    renderLoginForm()

    await user.type(screen.getByLabelText(/email/i), 'user@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    expect(
      await screen.findByText('Incorrect email or password.'),
    ).toBeInTheDocument()
    expect(getToken()).toBeNull()
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
