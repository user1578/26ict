// 端到端冒烟：本机 Edge（Chromium 内核）跑真实页面，验证
// 「创建 V1 → 上报晚点 → 决策坞 → 确认 V2 → 上报闭馆 → 确认 V3 → 版本档案 → 双主题 → 移动端 → mock」。
// 前置：B 后端 127.0.0.1:8000；Vite dev 127.0.0.1:5173（代理注入 X-Tool-Key）。
// 用法：node scripts/e2e-demo.mjs
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_URL ?? 'http://127.0.0.1:5173/'
const EDGE =
  process.env.EDGE_PATH ??
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const SHOTS = process.env.E2E_SHOTS ?? 'D:\\project\\audit\\screens-redesign'
mkdirSync(SHOTS, { recursive: true })

const steps = []
const pageErrors = []
let dockSeen = false

function shot(page, name, fullPage = false) {
  return page.screenshot({ path: `${SHOTS}\\${name}.png`, fullPage })
}

async function waitVersion(page, version, timeout = 20000) {
  await page.waitForFunction(
    (value) => {
      const meta = document.querySelector('.mission-meta')
      if (!meta || !meta.textContent) return false
      return meta.textContent.replace(/\s+/g, '').includes(`V${value}`)
    },
    version,
    { timeout },
  )
}

async function openSignal(page) {
  await page.getByTestId('open-signal').click()
  await page.getByTestId('signal-sheet').waitFor()
  await page.waitForTimeout(360)
}

const browser = await chromium.launch({ executablePath: EDGE, headless: true })
const context = await browser.newContext({
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
  viewport: { width: 1440, height: 960 },
})
const page = await context.newPage()
page.on('pageerror', (error) => pageErrors.push(String(error)))
page.on('console', (message) => {
  if (message.type() === 'error') pageErrors.push(`console: ${message.text()}`)
})

try {
  // ---------- 真实后端：主流程 ----------
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.getByTestId('create-trip').waitFor()
  await shot(page, '01-setup-dark')
  steps.push('setup (dark)')

  await page.getByTestId('create-trip').click()
  await page.getByTestId('budget-rail').waitFor({ timeout: 20000 })
  await waitVersion(page, 1)
  await page.getByTestId('agent-rail').waitFor()
  await shot(page, '02-console-v1-dark')
  steps.push('V1 console (dark)')

  await openSignal(page)
  await shot(page, '03-signal-sheet-dark')
  await page.getByTestId('signal-delay').click()
  await page.getByTestId('decision-dock').waitFor({ timeout: 20000 })
  await page.getByTestId('draft-card').first().waitFor()
  await page.waitForTimeout(520)
  await shot(page, '04-decision-delay-dark')
  steps.push('delay candidates (decision dock)')
  dockSeen = true

  await page.getByTestId('confirm-draft').first().click()
  await waitVersion(page, 2)
  await shot(page, '05-console-v2-dark')
  steps.push('V2 confirmed')

  await openSignal(page)
  await page.getByTestId('signal-closure').click()
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="draft-card"]').length >= 3,
    undefined,
    { timeout: 20000 },
  )
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll('[data-testid="draft-card"]')].filter((card) =>
        card.textContent?.includes('待确认'),
      ).length >= 2,
    undefined,
    { timeout: 20000 },
  )
  const cardCount = await page.getByTestId('draft-card').count()
  await page.waitForTimeout(520)
  await shot(page, '06-decision-closure-dark')
  steps.push(`closure candidates (${cardCount} cards)`)

  await page.getByTestId('confirm-draft').first().click()
  await waitVersion(page, 3)

  await page.getByTestId('open-history').click()
  await page.getByTestId('history-drawer').waitFor()
  await shot(page, '07-history-dark')
  steps.push('history drawer')
  await page.keyboard.press('Escape')
  await page.getByTestId('history-drawer').waitFor({ state: 'detached' })

  await page.getByTestId('theme-toggle').click()
  await page.waitForTimeout(900)
  const theme = await page.evaluate(() => document.documentElement.dataset.theme)
  await shot(page, '08-console-v3-light')
  const body = await page.locator('body').innerText()
  const checks = {
    hasV3: body.includes('V3'),
    hasSimulationLabel: body.includes('模拟'),
    hasAgentTrace: body.includes('智能体工作台'),
    hasDecisionDock: dockSeen || body.includes('决策坞'),
    lightTheme: theme === 'light',
  }
  await page.getByRole('button', { name: '重新开始' }).click()
  await page.getByTestId('create-trip').waitFor()
  await shot(page, '08b-setup-light')
  steps.push(`light theme (${theme})`)

  // ---------- 移动端 ----------
  const mobile = await browser.newContext({
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  const mobilePage = await mobile.newPage()
  mobilePage.on('pageerror', (error) => pageErrors.push(`mobile: ${String(error)}`))
  await mobilePage.goto(BASE, { waitUntil: 'networkidle' })
  await mobilePage.getByTestId('create-trip').waitFor()
  await shot(mobilePage, '09-mobile-setup')
  await mobilePage.getByTestId('create-trip').click()
  await mobilePage.getByTestId('budget-rail').waitFor({ timeout: 20000 })
  await mobilePage.getByTestId('open-signal').click()
  await mobilePage.getByTestId('signal-delay').click()
  await mobilePage.getByTestId('decision-dock').waitFor({ timeout: 20000 })
  await mobilePage.waitForTimeout(520)
  await shot(mobilePage, '10-mobile-decision')
  steps.push('mobile setup + decision')
  await mobile.close()

  // ---------- mock 模式 ----------
  const mock = await browser.newContext({
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1440, height: 960 },
  })
  const mockPage = await mock.newPage()
  mockPage.on('pageerror', (error) => pageErrors.push(`mock: ${String(error)}`))
  await mockPage.goto(`${BASE}?mode=mock`, { waitUntil: 'networkidle' })
  await mockPage.getByTestId('create-trip').click()
  await mockPage.getByTestId('budget-rail').waitFor({ timeout: 15000 })
  await mockPage.getByTestId('open-signal').click()
  await mockPage.getByTestId('signal-delay').click()
  await mockPage.getByTestId('decision-dock').waitFor({ timeout: 15000 })
  await mockPage.getByTestId('confirm-draft').first().click()
  await waitVersion(mockPage, 2)
  await mockPage.waitForTimeout(400)
  await shot(mockPage, '11-mock-v2')
  checks.mockV2 = (await mockPage.locator('.mission-meta').innerText()).replace(/\s+/g, '').includes('V2')
  steps.push('mock mode V2')
  await mock.close()

  console.log(JSON.stringify({ ok: true, steps, checks, pageErrors }, null, 2))
  if (pageErrors.length > 0) process.exitCode = 1
} catch (error) {
  await shot(page, '99-failure').catch(() => undefined)
  const text = await page.locator('body').innerText().catch(() => '')
  console.error('E2E FAILED:', error)
  console.error('--- page text tail ---')
  console.error(text.slice(-3000))
  console.log(JSON.stringify({ ok: false, steps, pageErrors }, null, 2))
  process.exitCode = 1
} finally {
  await browser.close()
}
