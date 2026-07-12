/** @type {import('tailwindcss').Config} */
//
// PAIOS — Nocturne (Warm Dark) design system.
// A calm, premium dark surface — dense data console, not editorial.
// - Warm dark surfaces (no pure black)
// - Three-tier text: primary / secondary / muted
// - Amber/gold accent for primary actions and active states
// - Muted warm green / gold / coral status pairs (NOT neon)
// - Inter only — no serif anywhere
// - Weights: 400 body, 500 headings/numbers (no 600/700)
//
// Token names preserved from Atelier (ink / sig / ok / warn / bad / violet)
// so semantic utility classes keep working; only underlying values change.
//
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Nocturne neutral ramp — dark surfaces at low numbers, text at high.
        // This keeps the 50=lightest / 950=darkest Tailwind convention while
        // mapping the old `ink-*` text classes to light-on-dark text values.
        ink: {
          50: '#302B25',    // surface-1 (main canvas bg)
          100: '#353029',   // surface-2 (cards / raised panels)
          200: '#45403A',   // border (hairline)
          300: '#55504A',   // border-strong (hover / dividers)
          400: '#80756B',   // placeholder / very muted text
          500: '#9C9187',   // text-muted (labels, timestamps)
          600: '#B8AC9C',   // text-secondary (body copy)
          700: '#C8BCAC',
          800: '#E0D4C2',
          900: '#F0E6D8',   // text-primary (headings, primary values)
          950: '#F5EDE0',
        },
        // Page surfaces.
        paper: '#302B25',   // surface-1 — main canvas (was warm paper)
        cream: '#353029',   // surface-2 — cards / raised (was warm cream)
        // Additional surface layers for direct use.
        surface: {
          0: '#2A2622',     // sidebar / darkest layer
          1: '#302B25',     // main canvas (same as paper)
          2: '#353029',     // cards / raised panels (same as cream)
        },
        // Primary signal — amber / gold. Warm, premium, calm.
        sig: {
          50: '#F5EDE0',    // light gold tint
          100: '#E8D6BE',
          200: '#E0B266',   // hover / sig-soft
          300: '#D4A24E',   // base accent (accent / sig)
          400: '#C89440',
          500: '#D4A24E',   // base accent (repeated for semantic mapping)
          600: '#C89440',
          700: '#BC8834',
          800: '#B07828',
          900: '#A46C1C',
          950: '#8C5810',
        },
        // Status tones — muted warm, NOT neon.
        ok: { 400: '#7FB878', 500: '#6DA866', 600: '#5D9656' },   // warm green
        warn: { 400: '#D4A24E', 500: '#C89440', 600: '#BC8834' }, // accent gold
        bad: { 400: '#D97A5F', 500: '#CF6A4D', 600: '#C05A3D' }, // warm coral
        violet: { 400: '#B89BD9', 500: '#A688CF', 600: '#9675C4' }, // muted plum
      },
      fontFamily: {
        // Inter for ALL text — no serif anywhere.
        display: ['Inter', 'system-ui', '"Segoe UI"', 'sans-serif'],
        sans: ['Inter', 'system-ui', '"Segoe UI"', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        'display-sm': ['1.625rem', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
        'display': ['2rem', { lineHeight: '1.1', letterSpacing: '-0.015em' }],
        'display-lg': ['2.75rem', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.25rem',
      },
      boxShadow: {
        // Layered shadows tuned for dark surface.
        card: '0 1px 2px rgba(0,0,0,0.28), 0 4px 12px -4px rgba(0,0,0,0.32)',
        'card-lg': '0 2px 4px rgba(0,0,0,0.28), 0 12px 32px -10px rgba(0,0,0,0.40)',
        soft: '0 1px 2px rgba(0,0,0,0.24)',
        ring: '0 0 0 3px rgba(212,162,78,0.22)',
        glow: '0 0 0 1px rgba(212,162,78,0.18), 0 6px 20px -10px rgba(212,162,78,0.30)',
        'glow-ok': '0 0 0 1px rgba(127,184,120,0.20), 0 6px 18px -10px rgba(127,184,120,0.30)',
        'glow-bad': '0 0 0 1px rgba(217,122,95,0.20), 0 6px 18px -10px rgba(217,122,95,0.30)',
      },
      keyframes: {
        pulseDot: {
          '0%,100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.45', transform: 'scale(0.82)' },
        },
        sweep: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
        riseIn: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        spinSlow: { to: { transform: 'rotate(360deg)' } },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        breathe: {
          '0%,100%': { transform: 'scale(1)', opacity: '0.85' },
          '50%': { transform: 'scale(1.06)', opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        pulseDot: 'pulseDot 1.4s ease-in-out infinite',
        sweep: 'sweep 1.6s ease-in-out infinite',
        riseIn: 'riseIn 0.28s ease-out both',
        spinSlow: 'spinSlow 2.4s linear infinite',
        fadeUp: 'fadeUp 0.4s ease-out both',
        breathe: 'breathe 4s ease-in-out infinite',
        shimmer: 'shimmer 2s linear infinite',
      },
    },
  },
  plugins: [],
}
