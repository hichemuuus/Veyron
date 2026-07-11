import { useEffect, useRef } from 'react'

/**
 * Declarative setInterval. Pass delay=null to pause.
 */
export function useInterval(callback: () => void, delay: number | null): void {
  const saved = useRef(callback)
  saved.current = callback

  useEffect(() => {
    if (delay == null) return
    const id = setInterval(() => saved.current(), delay)
    return () => clearInterval(id)
  }, [delay])
}
