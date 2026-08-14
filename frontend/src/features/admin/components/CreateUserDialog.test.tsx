import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { CreateUserDialog } from './CreateUserDialog'

const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast: mockToast }))

function renderDialog() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
  return render(<CreateUserDialog />, { wrapper: Wrapper })
}

async function openAndFill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /create user/i }))
  await user.type(await screen.findByLabelText(/email/i), 'new@example.com')
  await user.type(screen.getByLabelText(/password/i), 'correct-horse')
}

describe('CreateUserDialog', () => {
  afterEach(() => {
    mockToast.success.mockClear()
    mockToast.error.mockClear()
  })

  it('submits the form and closes the dialog on success', async () => {
    server.use(
      http.post('*/api/v1/users', () =>
        HttpResponse.json(
          {
            id: 'u1',
            email: 'new@example.com',
            role: 'member',
            is_active: true,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await openAndFill(user)
    await user.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() =>
      expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument(),
    )
  })

  it('shows the duplicate-email conflict as an inline form error, not a toast, and keeps the dialog open', async () => {
    server.use(
      http.post(
        '*/api/v1/users',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail: 'A user with this email already exists',
            }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await openAndFill(user)
    await user.click(screen.getByRole('button', { name: /^create$/i }))

    expect(
      await screen.findByText('A user with this email already exists'),
    ).toBeInTheDocument()
    // Inline, not silent: the field stays populated and the dialog stays open.
    expect(screen.getByLabelText(/email/i)).toHaveValue('new@example.com')
    // Not a toast: no sonner toast call happened for the error path.
    expect(mockToast.error).not.toHaveBeenCalled()
    expect(mockToast.success).not.toHaveBeenCalled()
  })
})
