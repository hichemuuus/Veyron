/** The PAIOS wordmark + mark. */

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <Mark size={size} />
      <div className="leading-none">
        <div className="text-[1.15rem] font-medium tracking-[-0.01em] text-ink-900">
          PAiOS
        </div>
        <div className="hud-label mt-1 text-[9px]">Nocturne · Intelligent Companion</div>
      </div>
    </div>
  )
}

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="paios-mark" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stopColor="#D17E58" />
          <stop offset="100%" stopColor="#A94A2D" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#paios-mark)" />
      {/* A stylized "P" companion glyph — open, friendly arc + node. */}
      <path
        d="M11 23 L11 9 L17.5 9 C20.5 9 22.5 11 22.5 13.8 C22.5 16.6 20.5 18.6 17.5 18.6 L11 18.6"
        fill="none"
        stroke="#FBF8F3"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22.5" cy="22.5" r="2.1" fill="#FBF8F3" opacity="0.92" />
    </svg>
  )
}
