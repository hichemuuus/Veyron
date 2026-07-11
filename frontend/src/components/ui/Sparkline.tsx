import { useMemo } from 'react'

interface SparklineProps {
  values: number[]
  /** 0-100 scale. values above max are clamped. */
  max?: number
  width?: number
  height?: number
  className?: string
  color?: string
}

/**
 * Lightweight inline SVG sparkline for live system metrics. Values are
 * rendered right-to-left (newest on the right).
 */
export function Sparkline({
  values,
  max = 100,
  width = 120,
  height = 28,
  className,
  color = '#52e6ff',
}: SparklineProps) {
  const path = useMemo(() => {
    if (values.length < 2) return ''
    const step = width / (values.length - 1)
    const pts = values.map((v, i) => {
      const y = height - (Math.min(Math.max(v, 0), max) / max) * (height - 2) - 1
      return `${(i * step).toFixed(1)},${y.toFixed(1)}`
    })
    return `M ${pts.join(' L ')}`
  }, [values, max, width, height])

  const area = useMemo(() => {
    if (!path) return ''
    return `${path} L ${width},${height} L 0,${height} Z`
  }, [path, width, height])

  const last = values[values.length - 1] ?? 0

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={`spark-${color}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {area && <path d={area} fill={`url(#spark-${color})`} />}
      {path && (
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
      {values.length > 0 && (
        <circle
          cx={width}
          cy={height - (Math.min(Math.max(last, 0), max) / max) * (height - 2) - 1}
          r="1.8"
          fill={color}
        />
      )}
    </svg>
  )
}
