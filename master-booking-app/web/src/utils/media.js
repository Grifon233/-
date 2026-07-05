export function resolveMediaUrl(value) {
  if (!value) return null

  const url = String(value).trim()
  if (!url) return null

  try {
    const parsed = new URL(url, window.location.origin)
    let path = parsed.pathname
    if (path.startsWith('/uploads/')) path = `/api${path}`

    if (path.startsWith('/api/uploads/')) {
      return `${path}${parsed.search}`
    }
  } catch {
    // The image fallback handles malformed legacy values.
  }

  return url
}
