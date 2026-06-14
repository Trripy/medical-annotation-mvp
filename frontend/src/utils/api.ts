const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

function normalizeApiBaseUrl(url: string): string {
  return url
    .replace(/\/+$/, '')
    .replace(/\/api\/v1$/, '')
    .replace(/\/api$/, '')
}

export const API_BASE_URL = configuredApiBaseUrl
  ? normalizeApiBaseUrl(configuredApiBaseUrl)
  : `${window.location.protocol}//${window.location.hostname}:8000`

export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

export function apiV1Url(path: string): string {
  return `${API_V1_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

export function resolveApiUrl(path: string | null | undefined): string {
  if (!path) {
    return ''
  }

  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }

  return apiUrl(path)
}
