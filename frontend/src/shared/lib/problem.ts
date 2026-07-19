import { isAxiosError } from 'axios'

const GENERIC_ERROR_MESSAGE = 'Something went wrong. Please try again.'

interface ProblemDetails {
  type?: string
  title?: string
  status?: number
  detail?: string
  instance?: string
}

function isProblemDetails(data: unknown): data is ProblemDetails {
  return (
    typeof data === 'object' &&
    data !== null &&
    ('title' in data || 'detail' in data)
  )
}

/**
 * Extracts a user-facing message from an RFC 7807 (application/problem+json)
 * error response. Falls back to a generic message for non-problem+json
 * bodies or non-Axios errors.
 */
export function parseProblemMessage(error: unknown): string {
  if (!isAxiosError(error)) {
    return GENERIC_ERROR_MESSAGE
  }

  const data = error.response?.data
  if (!isProblemDetails(data)) {
    return GENERIC_ERROR_MESSAGE
  }

  return data.detail ?? data.title ?? GENERIC_ERROR_MESSAGE
}
