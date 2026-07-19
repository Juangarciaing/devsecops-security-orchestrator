import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { SuppressButton } from './SuppressButton'

function renderButton(status: 'open' | 'suppressed') {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <SuppressButton findingId="f1" status={status} />
    </QueryClientProvider>,
  )
}

describe('SuppressButton', () => {
  it('shows a "Suppress" action for an open finding and posts suppress on click', async () => {
    const user = userEvent.setup()
    let requested = false
    server.use(
      http.post('*/api/v1/findings/f1/suppress', () => {
        requested = true
        return HttpResponse.json({ id: 'f1', status: 'suppressed' })
      }),
    )
    renderButton('open')

    const button = screen.getByRole('button', { name: /suppress/i })
    await user.click(button)

    await waitFor(() => expect(requested).toBe(true))
    await waitFor(() => expect(button).toBeEnabled())
  })

  it('shows an "Unsuppress" action for a suppressed finding and posts unsuppress on click', async () => {
    const user = userEvent.setup()
    let requested = false
    server.use(
      http.post('*/api/v1/findings/f1/unsuppress', () => {
        requested = true
        return HttpResponse.json({ id: 'f1', status: 'open' })
      }),
    )
    renderButton('suppressed')

    await user.click(screen.getByRole('button', { name: /unsuppress/i }))

    await waitFor(() => expect(requested).toBe(true))
  })

  it('leaves the button re-enabled and shows an error on failure', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(
        '*/api/v1/findings/f1/suppress',
        () =>
          new HttpResponse(
            JSON.stringify({ title: 'Conflict', detail: 'Cannot suppress' }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    renderButton('open')

    await user.click(screen.getByRole('button', { name: /suppress/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cannot suppress',
    )
    expect(screen.getByRole('button', { name: /suppress/i })).toBeEnabled()
  })
})
