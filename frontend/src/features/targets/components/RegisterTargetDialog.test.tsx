import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { RegisterTargetDialog } from './RegisterTargetDialog'

function renderDialog() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
  return render(<RegisterTargetDialog />, { wrapper: Wrapper })
}

async function openAndFill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /register target/i }))
  await user.type(await screen.findByLabelText(/^name$/i), 'staging web app')
  await user.type(
    screen.getByLabelText(/target url/i),
    'https://staging.example.com',
  )
}

describe('RegisterTargetDialog', () => {
  it('submits the form and closes the dialog on success', async () => {
    server.use(
      http.post('*/api/v1/targets', () =>
        HttpResponse.json(
          {
            id: 't1',
            name: 'staging web app',
            target_url: 'https://staging.example.com',
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
    await user.click(screen.getByRole('button', { name: /^register$/i }))

    await waitFor(() =>
      expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument(),
    )
  })

  it('shows an inline error and keeps the dialog open on conflict', async () => {
    server.use(
      http.post(
        '*/api/v1/targets',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail: 'A target with this URL already exists',
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
    await user.click(screen.getByRole('button', { name: /^register$/i }))

    expect(
      await screen.findByText('A target with this URL already exists'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument()
  })

  it('shows validation errors when required fields are missing', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: /register target/i }))
    await user.click(screen.getByRole('button', { name: /^register$/i }))

    expect(await screen.findAllByRole('alert')).not.toHaveLength(0)
  })
})
