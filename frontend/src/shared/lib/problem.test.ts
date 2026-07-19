import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { parseProblemMessage } from './problem'

function makeAxiosError(status: number, data: unknown) {
  return new AxiosError(
    'Request failed',
    String(status),
    undefined,
    undefined,
    {
      status,
      statusText: 'Error',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data,
    },
  )
}

describe('parseProblemMessage', () => {
  it('returns the RFC7807 "detail" field when present', () => {
    const error = makeAxiosError(401, {
      type: 'about:blank',
      title: 'Unauthorized',
      status: 401,
      detail: 'Incorrect email or password.',
    })

    expect(parseProblemMessage(error)).toBe('Incorrect email or password.')
  })

  it('falls back to "title" when "detail" is absent', () => {
    const error = makeAxiosError(404, {
      type: 'about:blank',
      title: 'Not Found',
      status: 404,
    })

    expect(parseProblemMessage(error)).toBe('Not Found')
  })

  it('returns a generic message when the response body is not RFC7807 shaped', () => {
    const error = makeAxiosError(500, 'Internal Server Error')

    expect(parseProblemMessage(error)).toBe(
      'Something went wrong. Please try again.',
    )
  })

  it('returns a generic message for a non-Axios error', () => {
    expect(parseProblemMessage(new Error('network down'))).toBe(
      'Something went wrong. Please try again.',
    )
  })
})
