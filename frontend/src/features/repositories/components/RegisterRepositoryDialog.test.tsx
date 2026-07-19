import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { RegisterRepositoryDialog } from './RegisterRepositoryDialog'

function renderDialog() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
  return render(<RegisterRepositoryDialog />, { wrapper: Wrapper })
}

async function openAndFill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /register repository/i }))
  await user.type(await screen.findByLabelText(/owner/i), 'acme')
  await user.type(screen.getByLabelText(/^name$/i), 'widgets')
  await user.type(
    screen.getByLabelText(/clone url/i),
    'https://github.com/acme/widgets.git',
  )
  await user.type(screen.getByLabelText(/default branch/i), 'main')
}

describe('RegisterRepositoryDialog', () => {
  it('submits the form and closes the dialog on success', async () => {
    server.use(
      http.post('*/api/v1/repositories', () =>
        HttpResponse.json(
          {
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
      expect(screen.queryByLabelText(/owner/i)).not.toBeInTheDocument(),
    )
  })

  it('shows an inline error and keeps the dialog open on conflict', async () => {
    server.use(
      http.post(
        '*/api/v1/repositories',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail:
                'A repository with this provider/owner/name already exists',
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
      await screen.findByText(
        'A repository with this provider/owner/name already exists',
      ),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/owner/i)).toBeInTheDocument()
  })

  it('shows validation errors when required fields are missing', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(
      screen.getByRole('button', { name: /register repository/i }),
    )
    await user.click(screen.getByRole('button', { name: /^register$/i }))

    expect(await screen.findAllByRole('alert')).not.toHaveLength(0)
  })
})
