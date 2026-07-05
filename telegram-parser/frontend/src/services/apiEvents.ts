/**
 * Global API error event bus.
 *
 * Components subscribe to ``api:error`` and ``api:network-down`` events
 * via ``subscribeApiError()`` and re-render with the latest payload.
 *
 * Why this exists
 * ---------------
 * The UI used to swallow every API failure with a single
 * ``console.error`` and fall back to mock data, so the operator had no
 * way to tell a real backend outage from "I have 5 accounts". The
 * ``api.ts`` interceptor now dispatches a CustomEvent on every error;
 * a single ``ApiErrorBanner`` mounted in ``App.tsx`` shows it.
 */
export type ApiErrorLevel = 'error' | 'warning' | 'info'

export interface ApiErrorPayload {
  /** Short headline, e.g. "Бэкенд недоступен" or "401 Unauthorized". */
  title: string
  /** Optional longer description. */
  detail?: string
  /** Severity; defaults to ``error``. */
  level?: ApiErrorLevel
  /** HTTP status if known. */
  status?: number
  /** Request method + URL for debugging. */
  request?: string
  /** Unix ms when the error happened. */
  at: number
}

const TARGET =
  typeof window !== 'undefined' ? window : (globalThis as unknown as EventTarget)

export function emitApiError(payload: Omit<ApiErrorPayload, 'at'>) {
  const event = new CustomEvent<ApiErrorPayload>('api:error', {
    detail: { ...payload, at: Date.now() },
  })
  TARGET.dispatchEvent(event)
}

export function subscribeApiError(
  handler: (payload: ApiErrorPayload) => void,
): () => void {
  const listener = (event: Event) => {
    const custom = event as CustomEvent<ApiErrorPayload>
    handler(custom.detail)
  }
  TARGET.addEventListener('api:error', listener as EventListener)
  return () => TARGET.removeEventListener('api:error', listener as EventListener)
}
