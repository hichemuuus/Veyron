/**
 * Phase 17.6 — Desktop Reality Check
 *
 * Uses Playwright to open every page of the Veyron frontend in a headless
 * Chromium browser, checks for JavaScript errors, takes screenshots, and
 * exercises real task creation through the UI.
 */
const { chromium } = require('playwright')

const BASE = 'http://localhost:5173'
const BACKEND = 'http://127.0.0.1:8000'

const errors = []
const allLogs = []

function captureConsole(page) {
  page.on('console', (msg) => {
    allLogs.push(`[${msg.type()}] ${msg.text()}`)
    if (msg.type() === 'error') errors.push(msg.text())
  })
  page.on('pageerror', (err) => {
    errors.push(`PAGE ERROR: ${err.message}`)
    allLogs.push(`[pageerror] ${err.message}`)
  })
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

;(async () => {
  console.log('=== Phase 17.6 — Veyron Desktop Reality Check ===\n')

  // Verify backend first
  console.log('--- Verifying backend ---')
  try {
    const r = await fetch(`${BACKEND}/api/health`)
    const body = await r.json()
    console.log(`  BACKEND: ${JSON.stringify(body)}`)
  } catch (e) {
    console.error(`  BACKEND UNREACHABLE: ${e.message}`)
  }

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  })

  // ──────────────────────────────────────────────────────────────
  // STEP 2: Navigate every page, check for errors, screenshot
  // ──────────────────────────────────────────────────────────────
  const routes = [
    '/',
    '/dashboard',
    '/tasks',
    '/memory',
    '/learning',
    '/projects',
    '/tools',
    '/agent',
  ]

  for (const route of routes) {
    const page = await context.newPage()
    captureConsole(page)
    console.log(`\n--- Navigating to ${route} ---`)
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 25000 })
      await sleep(2000)

      const title = await page.title()
      const text = (await page.locator('body').innerText()).slice(0, 300)

      await page.screenshot({ path: `screenshot_${route.replace(/\//g, '_') || 'root'}.png`, fullPage: true })
      console.log(`  Title: ${title}`)
      console.log(`  Content: ${text.replace(/\n/g, ' | ')}`)
    } catch (e) {
      console.error(`  NAV ERROR ${route}: ${e.message}`)
      errors.push(`NAV ${route}: ${e.message}`)
    }
    const routeErrors = allLogs.filter(l => l.startsWith('[error]'))
    if (routeErrors.length > 0) {
      console.log(`  Console errors on ${route}: ${routeErrors.slice(-3).join('; ')}`)
    }
    await page.close()
  }

  // ──────────────────────────────────────────────────────────────
  // STEP 3: Create a real task via the UI
  // ──────────────────────────────────────────────────────────────
  console.log('\n--- Creating a task via Agent workspace ---')
  const agentPage = await context.newPage()
  captureConsole(agentPage)

  try {
    await agentPage.goto(`${BASE}/agent`, { waitUntil: 'networkidle', timeout: 25000 })
    await sleep(2000)

    // Type goal
    const textarea = agentPage.locator('textarea')
    await textarea.waitFor({ state: 'visible', timeout: 10000 })
    await textarea.fill('Check CPU and memory usage')
    console.log('  Typed goal')
    await sleep(300)

    // Click Run
    const runBtn = agentPage.locator('button', { hasText: /^Run/ })
    await runBtn.waitFor({ state: 'visible', timeout: 5000 })
    await runBtn.click()
    console.log('  Clicked Run')

    // Wait for the task to initialize
    await sleep(5000)
    await agentPage.screenshot({ path: 'screenshot_task_started.png', fullPage: true })
    console.log('  Screenshot: screenshot_task_started.png (5s after submit)')

    // Show visible status
    const bodyAfter = await agentPage.locator('body').innerText()
    console.log(`  Visible state: ${bodyAfter.slice(0, 600).replace(/\n/g, ' | ')}`)

    // Wait for task to fail (no Ollama)
    console.log('  Waiting for task to fail (~18s)...')
    await sleep(18000)
    await agentPage.screenshot({ path: 'screenshot_task_final.png', fullPage: true })
    console.log('  Screenshot: screenshot_task_final.png (~23s after submit)')

    const finalBody = await agentPage.locator('body').innerText()
    console.log(`  Final state: ${finalBody.slice(0, 600).replace(/\n/g, ' | ')}`)
  } catch (e) {
    console.error(`  TASK ERROR: ${e.message}`)
    errors.push(`TASK: ${e.message}`)
  }
  await agentPage.close()

  // ──────────────────────────────────────────────────────────────
  // Summary
  // ──────────────────────────────────────────────────────────────
  console.log('\n========================================')
  console.log('=== RESULTS ===')
  console.log(`JavaScript errors: ${errors.length}`)
  if (errors.length > 0) {
    console.log('Error list:')
    errors.forEach((e, i) => console.log(`  ${i + 1}. ${e}`))
  }
  console.log(`Console log entries: ${allLogs.length}`)

  // Check for known bad patterns
  const body = allLogs.join('\n')
  const patterns = [
    ['TypeError: t is not iterable', 'OLD BUG — Task list crash'],
    ['task.status: running.*before.*backend', 'FAKE RUNNING — optimistic status'],
    ['Cannot read properties of undefined', 'UNDEFINED ACCESS'],
  ]
  console.log('\n--- Known issue scan ---')
  for (const [pattern, label] of patterns) {
    const found = body.includes(pattern)
    console.log(`  ${label}: ${found ? 'FOUND ✗' : 'NOT FOUND ✓'}`)
  }

  await browser.close()
  console.log('\n=== Phase 17.6 verification complete ===')
})()
