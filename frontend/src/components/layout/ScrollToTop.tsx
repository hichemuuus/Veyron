import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Scrolls the main content area to the top on every route change.
 * Placed inside <BrowserRouter> so it has access to location.
 */
export function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}
