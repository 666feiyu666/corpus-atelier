import type { ErrorEnvelope } from '~/types'

/** A refused call, carrying the boundary's own error code. */
export class ApiFailure extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiFailure'
    this.status = status
    this.code = code
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** The header the Python boundary stamps on every response it sends. */
const SERVICE_HEADER = 'X-Corpus-Atelier'
const SERVICE_NAME = 'corpus-atelier'

/**
 * The one place that talks to the Python boundary. Responses are already
 * projected (no paths, no keys), so pages can render them directly.
 */
export function useApi() {
  const config = useRuntimeConfig()
  const base = String(config.public.apiBase ?? '').replace(/\/+$/, '')

  function absolute(path: string): string {
    return path.startsWith('http') ? path : `${base}${path.startsWith('/') ? '' : '/'}${path}`
  }

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response
    try {
      response = await fetch(absolute(path), {
        method,
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      throw new ApiFailure(0, 'unreachable', 'Cannot reach the local API.')
    }
    if (response.headers.get(SERVICE_HEADER) !== SERVICE_NAME) {
      // Something else answers on that port — most likely another local project.
      // Its JSON can look close enough to ours to be misread, so refuse it here
      // rather than report a confusing bug against this interface.
      throw new ApiFailure(
        0,
        'wrong_service',
        `The service answering on ${base || 'this origin'} is not the Corpus Atelier API. `
          + 'Another local project may be using that port; start this one with '
          + '`corpus-atelier start`, or point the interface at its own port.',
      )
    }
    if (response.status === 204) {
      return undefined as T
    }
    const text = await response.text()
    const payload = text ? safeJson(text) : null
    if (!response.ok) {
      const envelope = payload as ErrorEnvelope | null
      throw new ApiFailure(
        response.status,
        envelope?.error?.code ?? 'internal_error',
        envelope?.error?.message ?? `HTTP ${response.status}`,
      )
    }
    return payload as T
  }

  return {
    base,
    absolute,
    get: <T>(path: string) => request<T>('GET', path),
    post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
    put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
    del: <T>(path: string) => request<T>('DELETE', path),
  }
}
