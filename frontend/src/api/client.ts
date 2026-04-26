export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000'

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const raw = await response.text().catch(() => '')
    let parsed: unknown = raw
    let message = `API ${response.status}`
    try {
      parsed = raw ? JSON.parse(raw) : undefined
      const body = parsed as { detail?: unknown } | undefined
      if (typeof body?.detail === 'string') {
        message = body.detail
      } else if (raw) {
        message = raw
      }
    } catch {
      if (raw) {
        message = raw
      }
    }
    throw new ApiError(response.status, message, parsed)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text().catch(() => '')
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  return parseResponse<T>(response)
}