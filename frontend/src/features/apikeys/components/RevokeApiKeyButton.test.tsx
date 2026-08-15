import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { RevokeApiKeyButton } from './RevokeApiKeyButton'

function renderButton() {
  const queryClient = createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
  return render(<RevokeApiKeyButton keyId="k1" />, { wrapper: Wrapper })
}

describe('RevokeApiKeyButton', () => {
  it('revokes the key on confirm and invalidates the list query', async () => {
    server.use(
      http.post('*/api/v1/auth/api-keys/k1/revoke', () =>
        HttpResponse.json({
          id: 'k1',
          user_id: 'u1',
          key_prefix: 'sk_ab12',
          is_active: false,
          created_at: '2026-01-01T00:00:00Z',
          last_used_at: null,
          revoked_at: '2026-01-02T00:00:00Z',
        }),
      ),
    )
    const user = userEvent.setup()
    renderButton()

    const revokeButton = await screen.findByRole('button', { name: /revoke/i })
    await user.click(revokeButton)
    await user.click(await screen.findByRole('button', { name: /confirm/i }))

    await waitFor(() =>
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(),
    )
  })
})
