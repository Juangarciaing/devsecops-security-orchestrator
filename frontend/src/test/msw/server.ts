import { setupServer } from 'msw/node'

// Shared MSW node server for container/integration tests. Individual test
// files register request handlers via `server.use(...)`; the base handler
// list stays empty so every test is explicit about what it mocks.
export const server = setupServer()
