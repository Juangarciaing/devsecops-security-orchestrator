import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, setToken } from '@/shared/api/token'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useScanEvents } from './useScanEvents'

type FakeListener = (event: unknown) => void

// Hand-rolled fake `EventSource`: jsdom does not implement `EventSource`
// (confirmed: `typeof new JSDOM().window.EventSource === 'undefined'`), and
// this codebase avoids adding a test dependency for a single hook — matching
// the design's own "fakeredis-free hand-rolled fake" testing-strategy note
// for the backend relay tests.
class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  closed = false
  private listeners: Record<string, FakeListener[]> = {}

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: FakeListener): void {
    const bucket = this.listeners[type] ?? []
    bucket.push(listener)
    this.listeners[type] = bucket
  }

  removeEventListener(type: string, listener: FakeListener): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter(
      (registered) => registered !== listener,
    )
  }

  close(): void {
    this.closed = true
  }

  emit(type: string, event: unknown): void {
    for (const listener of this.listeners[type] ?? []) {
      listener(event)
    }
  }
}

function statusEvent(status: string) {
  return {
    data: JSON.stringify({
      scan_run_id: 's1',
      status,
      at: '2026-01-01T00:00:00Z',
    }),
  }
}

function renderWithClient(id: string, queryClient: QueryClient) {
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    )
  }
  return renderHook(() => useScanEvents(id), { wrapper })
}

describe('useScanEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    setToken('test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearToken()
  })

  it('does not open a connection without a token', () => {
    clearToken()
    const queryClient = createTestQueryClient()
    const { result } = renderWithClient('s1', queryClient)

    expect(FakeEventSource.instances).toHaveLength(0)
    expect(result.current.live).toBe(false)
  })

  it('does not open a connection without an id', () => {
    const queryClient = createTestQueryClient()
    const { result } = renderWithClient('', queryClient)

    expect(FakeEventSource.instances).toHaveLength(0)
    expect(result.current.live).toBe(false)
  })

  it('sets live true on open and false on error', async () => {
    const queryClient = createTestQueryClient()
    const { result } = renderWithClient('s1', queryClient)

    const source = FakeEventSource.instances[0]
    expect(source).toBeDefined()
    expect(result.current.live).toBe(false)

    act(() => source.emit('open', {}))
    await waitFor(() => expect(result.current.live).toBe(true))

    act(() => source.emit('error', {}))
    await waitFor(() => expect(result.current.live).toBe(false))
  })

  it('invalidates the scan query on a scan.status message and never writes cache data directly', () => {
    const queryClient = createTestQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const setDataSpy = vi.spyOn(queryClient, 'setQueryData')
    renderWithClient('s1', queryClient)

    const source = FakeEventSource.instances[0]
    act(() => source.emit('scan.status', statusEvent('running')))

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['scans', 's1'] })
    expect(setDataSpy).not.toHaveBeenCalled()
  })

  it('closes the stream on a terminal scan.status event (client-side close is load-bearing)', () => {
    const queryClient = createTestQueryClient()
    renderWithClient('s1', queryClient)

    const source = FakeEventSource.instances[0]
    act(() => source.emit('scan.status', statusEvent('completed')))

    expect(source.closed).toBe(true)
  })

  it('does not close the stream on a non-terminal scan.status event', () => {
    const queryClient = createTestQueryClient()
    renderWithClient('s1', queryClient)

    const source = FakeEventSource.instances[0]
    act(() => source.emit('scan.status', statusEvent('running')))

    expect(source.closed).toBe(false)
  })

  it('does not manually open a new connection in response to error (browser owns reconnect)', () => {
    const queryClient = createTestQueryClient()
    renderWithClient('s1', queryClient)

    const source = FakeEventSource.instances[0]
    act(() => source.emit('error', {}))

    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('closes the connection on unmount, including a React StrictMode double-mount', () => {
    const queryClient = createTestQueryClient()
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <StrictMode>
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        </StrictMode>
      )
    }
    const { unmount } = renderHook(() => useScanEvents('s1'), {
      wrapper: Wrapper,
    })

    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(1)
    unmount()

    for (const source of FakeEventSource.instances) {
      expect(source.closed).toBe(true)
    }
  })
})
