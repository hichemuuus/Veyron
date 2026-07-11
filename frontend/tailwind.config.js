/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Deep control-room surfaces.
        ink: {
          950: '#070b12',
          900: '#0a0f18',
          850: '#0e1420',
          800: '#121a28',
          750: '#161f30',
          700: '#1b2536',
          600: '#243047',
          500: '#33425c',
          400: '#4a5a76',
        },
        // Primary signal — cyan-teal.
        sig: {
          50: '#ecffff',
          100: '#c9fbff',
          200: '#95f3ff',
          300: '#52e6ff',
          400: '#1ed3f4',
          500: '#06b4d8',
          600: '#0890b4',
          700: '#0c7290',
          800: '#115c75',
          900: '#134c62',
        },
        ok: { 400: '#3fd7a3', 500: '#16c089', 600: '#0a9a6e' },
        warn: { 400: '#f6c453', 500: '#eaa422', 600: '#c7830a' },
        bad: { 400: '#ff7a85', 500: '#f5525f', 600: '#dc2f3d' },
        violet: { 400: '#a98bff', 500: '#8b5cf6' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.7)',
        glow: '0 0 0 1px rgba(30,211,244,0.25), 0 0 20px -4px rgba(30,211,244,0.35)',
        'glow-ok': '0 0 0 1px rgba(22,192,137,0.25), 0 0 18px -6px rgba(22,192,137,0.4)',
        'glow-bad': '0 0 0 1px rgba(245,82,95,0.25), 0 0 18px -6px rgba(245,82,95,0.4)',
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(30,211,244,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(30,211,244,0.04) 1px, transparent 1px)",
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
      },
      animation: {
        pulseDot: 'pulseDot 1.4s ease-in-out infinite',
        sweep: 'sweep 1.6s ease-in-out infinite',
        riseIn: 'riseIn 0.28s ease-out both',
        spinSlow: 'spinSlow 2.4s linear infinite',
      },
    },
  },
  plugins: [],
}
