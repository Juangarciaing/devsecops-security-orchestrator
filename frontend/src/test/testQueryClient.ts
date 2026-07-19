import { QueryClient } from '@tanstack/react-query'

/**
 * A QueryClient tuned for tests: no retries (so failures surface
 * immediately) and no cache persistence across test files.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}
