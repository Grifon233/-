import axios from 'axios'

import { emitApiError } from './apiEvents'

// Backend URL. Order of precedence:
//   1. VITE_API_URL  — explicit override (set in frontend/.env).
//   2. http://127.0.0.1:8000 — uvicorn default for local dev.
//   3. http://localhost:8000  — fallback.
// Earlier revisions hard-coded :8005 here, which silently desynced the
// UI from the backend whenever the dev port changed.
const API_BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ||
  'http://127.0.0.1:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  proxy: false,
})

// Admin token. Read in this order so the operator can override the
// built-in value at runtime:
//   1. localStorage('admin_api_token')   — set by the Settings page.
//   2. import.meta.env.VITE_ADMIN_API_TOKEN — set in frontend/.env.
// Without this fallback, every request hit the ``require_admin_token``
// dependency on the backend and got a 401, which made the UI fall back
// to mock data and hide real backend problems.
function resolveAdminToken(): string {
  const fromStorage = localStorage.getItem('admin_api_token')
  if (fromStorage) return fromStorage
  const fromEnv = import.meta.env.VITE_ADMIN_API_TOKEN as string | undefined
  return fromEnv || ''
}

// Request interceptor for auth + project context.
api.interceptors.request.use(
  (config) => {
    const token = resolveAdminToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    } else {
      // Make sure we don't accidentally send a stale value from a
      // previous session.
      delete config.headers.Authorization
    }
    config.headers['X-Project-ID'] = localStorage.getItem('active_project_id') || '1'
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor: keep the original error but attach a hint when
// the network is unreachable so debugging is easier. We also dispatch
// a global ``api:error`` event so the UI can show a banner without
// each page having to wire up its own toast.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const request = `${error.config?.method?.toUpperCase() ?? ''} ${error.config?.url ?? ''}`.trim()
    const detailFromServer =
      typeof error.response?.data?.detail === 'string'
        ? error.response.data.detail
        : undefined

    if (error.code === 'ERR_NETWORK' || error.message?.includes('Network Error')) {
      // eslint-disable-next-line no-console
      console.error(`[API] Network error — backend at ${API_BASE_URL} is unreachable`)
      emitApiError({
        title: 'Бэкенд недоступен',
        detail: `Не удалось подключиться к ${API_BASE_URL}. Проверьте, что backend запущен.`,
        level: 'error',
        request,
      })
    } else if (status === 401) {
      // eslint-disable-next-line no-console
      console.warn('[API] 401 Unauthorized — admin_api_token missing or invalid')
      emitApiError({
        title: 'Требуется авторизация',
        detail:
          detailFromServer ??
          'Проверьте VITE_ADMIN_API_TOKEN в frontend/.env и ADMIN_API_TOKEN в backend/.env',
        level: 'warning',
        status,
        request,
      })
    } else if (status && status >= 500) {
      emitApiError({
        title: `Ошибка сервера ${status}`,
        detail: detailFromServer ?? 'Бэкенд сообщил о внутренней ошибке',
        level: 'error',
        status,
        request,
      })
    } else if (status === 422) {
      // 422 is almost always user-facing (validation). Surface it
      // inline where it happened; here we only log to avoid spamming
      // the global banner on every form submit.
      // eslint-disable-next-line no-console
      console.warn('[API] 422 validation error', error.response?.data)
    }
    return Promise.reject(error)
  }
)

export default api
