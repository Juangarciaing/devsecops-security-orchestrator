import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { IssueApiKeyDialog } from './IssueApiKeyDialog'

function renderDialog() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
  return render(<IssueApiKeyDialog />, { wrapper: Wrapper })
}

async function issueKey(user: ReturnType<typeof userEvent.setup>, rawKey: string) {
  server.use(
    http.post('*/api/v1/auth/api-keys', () =>
      HttpResponse.json(
        {
          api_key: {
            id: 'k1',
            user_id: 'u1',
            key_prefix: 'sk_ab12',
            is_active: true,
            created_at: '2026-01-01T00:00:00Z',
            last_used_at: null,
            revoked_at: null,
          },
          raw_key: rawKey,
        },
        { status: 201 },
      ),
    ),
  )
  await user.click(screen.getByRole('button', { name: /issue new key/i }))
  await user.click(screen.getByRole('button', { name: /^issue key$/i }))
  await screen.findByText(rawKey)
}

describe('IssueApiKeyDialog', () => {
  it('reveals the raw key once, blocks outside-close, gates Done on the ack checkbox, and clears state on close (D7)', async () => {
    const user = userEvent.setup()
    // Spy AFTER setup() — it attaches its own Clipboard stub to `navigator`.
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined)
    renderDialog()

    await issueKey(user, 'sk_ab12cd34ef56')

    await user.click(screen.getByRole('button', { name: /^copy$/i }))
    expect(writeText).toHaveBeenCalledWith('sk_ab12cd34ef56')

    // Radix flags outside interaction via `pointerdown` on `document`;
    // dispatch on the overlay directly since `<body>` gets pointer-events:
    // none while modal, which blocks `user.click` before Radix ever sees it.
    await user.keyboard('{Escape}')
    const overlay = document.querySelector('[data-slot="dialog-overlay"]')
    fireEvent.pointerDown(overlay as Element)
    expect(screen.getByText('sk_ab12cd34ef56')).toBeInTheDocument()

    const doneButton = screen.getByRole('button', { name: /^done$/i })
    expect(doneButton).toBeDisabled()
    await user.click(screen.getByLabelText(/i have copied this key/i))
    expect(doneButton).toBeEnabled()

    await user.click(doneButton)
    await waitFor(() =>
      expect(screen.queryByText('sk_ab12cd34ef56')).not.toBeInTheDocument(),
    )

    // Reopening must never show the same key again — mutation.reset() ran.
    await user.click(screen.getByRole('button', { name: /issue new key/i }))
    expect(screen.queryByText('sk_ab12cd34ef56')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /^issue key$/i }),
    ).toBeInTheDocument()
  })
})
