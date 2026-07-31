import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './msw/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// jsdom does not implement `EventSource` (verified against a bare JSDOM
// instance: `typeof window.EventSource === 'undefined'`). This minimal
// no-op stub lets any component that opens a real one (`useScanEvents`)
// mount without a `ReferenceError` in tests that never assert on SSE
// behavior itself — e.g. `goldenPath.test.tsx`'s full login-through-scan
// walk. Tests that DO assert on SSE lifecycle (`useScanEvents.test.tsx`)
// override this with a richer hand-rolled fake via `vi.stubGlobal`.
if (typeof globalThis.EventSource === 'undefined') {
  class NoopEventSource {
    addEventListener(): void {}
    removeEventListener(): void {}
    close(): void {}
  }
  globalThis.EventSource = NoopEventSource as unknown as typeof EventSource
}
