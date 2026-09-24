import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'

/** Fetch JSON with optional polling. `refresh()` re-fetches immediately. */
export function useApi<T>(path: string | null, opts: { poll?: number | false } = {}) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const pathRef = useRef(path)
  pathRef.current = path

  const load = useCallback(async () => {
    if (!pathRef.current) return
    try {
      const d = await api.get<T>(pathRef.current)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
  }, [path, load])

  useEffect(() => {
    if (!opts.poll) return
    const id = window.setInterval(load, opts.poll)
    return () => window.clearInterval(id)
  }, [opts.poll, load])

  return { data, error, loading, refresh: load, setData }
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}
