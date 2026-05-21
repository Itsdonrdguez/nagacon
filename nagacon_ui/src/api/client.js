import axios from 'axios'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.PROD ? '' : 'http://127.0.0.1:8000')

const SESSION_STORAGE_KEY = 'nagacon_session_token'
const ENABLE_SESSION_TOKEN_DIAGNOSTICS = String(import.meta.env.VITE_ENABLE_SESSION_TOKEN_DIAGNOSTICS ?? 'false').toLowerCase() === 'true'

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (ENABLE_SESSION_TOKEN_DIAGNOSTICS && typeof window !== 'undefined') {
    const token = window.localStorage.getItem(SESSION_STORAGE_KEY)
    if (token) {
      config.headers = config.headers || {}
      config.headers['X-Session-Token'] = token
    }
  }
  return config
})

export function persistSessionToken(token) {
  if (typeof window === 'undefined') {
    return
  }
  if (!ENABLE_SESSION_TOKEN_DIAGNOSTICS) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY)
    return
  }
  if (token) {
    window.localStorage.setItem(SESSION_STORAGE_KEY, token)
  } else {
    window.localStorage.removeItem(SESSION_STORAGE_KEY)
  }
}
