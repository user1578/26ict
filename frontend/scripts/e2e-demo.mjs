// Real browser + real B HTTP. Provider facts for lifecycle tests are explicitly simulated.
// Live provider evidence is tested separately against the normal local service.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { randomBytes } from 'node:crypto'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..')
const root=resolve(frontend,'..')
const shots=resolve(process.env.E2E_SHOTS ?? resolve(root,'.cache/integration/screenshots'))
const python=process.env.E2E_PYTHON ?? resolve(root,'backend/.venv/Scripts/python.exe')
const edge=process.env.EDGE_PATH ?? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const liveBase=process.env.E2E_URL ?? 'http://127.0.0.1:5174/'
mkdirSync(shots,{recursive:true})
const children=[]
const logs=[]
const errors=[]
const steps=[]
let browser
const freePort=()=>new Promise((resolvePort,reject)=>{
  const s=createServer();s.on('error',reject);s.listen(0,'127.0.0.1',()=>{const {port}=s.address();s.close(()=>resolvePort(port))})
})
const launch=(exe,args,env)=>{
  const child=spawn(exe,args,{cwd:frontend,env:{...process.env,...env},windowsHide:true,stdio:['ignore','pipe','pipe']})
  children.push(child)
  child.stdout.on('data',x=>logs.push(String(x)))
  child.stderr.on('data',x=>logs.push(String(x)))
  return child
}
async function ready(url,child){
  const deadline=Date.now()+20000
  while(Date.now()<deadline){
    if(child.exitCode!==null) throw new Error(`Service startup failed: ${logs.join('').slice(-1500)}`)
    try { const r=await fetch(url);if(r.ok)return } catch { /* bounded startup probe */ }
    await new Promise(r=>setTimeout(r,100))
  }
  throw new Error(`Service readiness timeout: ${url}`)
}
const shot=(page,name)=>page.screenshot({path:resolve(shots,`${name}.png`),fullPage:false})
async function version(page,n){await page.waitForFunction(v=>document.querySelector('.mission-meta')?.textContent?.replace(/\s/g,'').includes(`V${v}`),n)}
async function fill(page,city='杭州'){
  await page.getByTestId('field-city').fill(city)
  await page.getByTestId('field-origin').fill('上海')
  const dates=page.locator('input[type="date"]')
  await dates.nth(0).fill('2026-11-10');await dates.nth(1).fill('2026-11-11')
  await page.getByText('其他费用估算', {exact:false}).locator('..').locator('input').fill('200')
  await page.getByText('同行人数', {exact:false}).locator('..').locator('input').fill('2')
}
async function verifyFixtureEvent(page){
  const tripId=new URL(page.url()).searchParams.get('trip')
  const trip=await (await page.request.get(`/api/trips/${tripId}`)).json()
  const event=trip.events.at(-1)
  const {event_id,revision:_revision,...facts}=event
  const response=await page.request.put(`/api/trips/${tripId}/events/${event_id}`,{data:{...facts,
    request_id:`e2e-verify-${randomBytes(4).toString('hex')}`,expected_event_revision:trip.event_revision,
    source:'simulation',evidence_ref:'simulation:e2e-controlled-verification',verification_status:'verified'}})
  assert.equal(response.status(),200)
  await page.reload({waitUntil:'networkidle'})
  await page.getByTestId('refresh-recommendations').click()
  await page.getByTestId('decision-dock').waitFor()
  await page.getByTestId('confirm-draft').filter({visible:true}).first().waitFor()
}
try {
  const apiPort=await freePort(), uiPort=await freePort(), key=`e2e-${randomBytes(16).toString('hex')}`
  const env={TRAVELGUARD_TOOL_API_KEY:key,TRAVELGUARD_TOOL_KEY:key,
    TRAVELGUARD_DB_PATH:resolve(root,`backend/.pytest_cache/e2e-${process.pid}.local.sqlite3`),
    E2E_BACKEND_PORT:String(apiPort),TRAVELGUARD_API_BASE:`http://127.0.0.1:${apiPort}`}
  const backend=launch(python,[resolve(root,'backend/tests/e2e_server.py')],env)
  await ready(`http://127.0.0.1:${apiPort}/health`,backend)
  const vite=launch(process.execPath,[resolve(frontend,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(uiPort),'--strictPort'],env)
  const base=`http://127.0.0.1:${uiPort}/`
  await ready(base,vite)
  browser=await chromium.launch({executablePath:edge,headless:true})
  const context=await browser.newContext({baseURL:base,locale:'zh-CN',timezoneId:'Asia/Shanghai',viewport:{width:1440,height:960}})
  const page=await context.newPage();page.setDefaultTimeout(20000)
  page.on('pageerror',e=>errors.push(String(e)))
  await page.goto(base,{waitUntil:'networkidle'})
  await fill(page)
  await shot(page,'01-setup-dark')
  assert.equal(await page.locator('.mode-link').count(),0)
  assert.equal(await page.getByText('生成 V1 并启动智能体',{exact:true}).count(),0)
  await page.getByTestId('create-trip').click()
  await page.getByTestId('recommendation-card').first().waitFor()
  assert.equal(await page.getByTestId('recommendation-card').count(),3)
  assert.match(await page.getByTestId('recommendations').innerText(),/模拟数据/)
  await page.getByTestId('recommendations').scrollIntoViewIfNeeded()
  await shot(page,'02-controlled-recommendations')
  assert.equal(await page.getByTestId('save-recommendation').isEnabled(),true)
  await page.getByTestId('save-recommendation').click();await version(page,1)
  steps.push('real B HTTP with simulated evidence: 3 alternatives -> select -> V1')
  const savedContext=await page.evaluate(()=>{const key=`travelguard:planning:${new URL(location.href).searchParams.get('trip')}`; const value=localStorage.getItem(key);localStorage.removeItem(key);return {key,value}})
  await page.reload({waitUntil:'networkidle'});await version(page,1)
  await page.getByTestId('open-signal').click();await page.getByTestId('signal-delay').click()
  await page.getByRole('alert').filter({hasText:'缺少此旅行的规划上下文'}).waitFor()
  const unchanged=await (await page.request.get(`/api/trips/${new URL(page.url()).searchParams.get('trip')}`)).json()
  assert.equal(unchanged.event_revision,0)
  await page.evaluate(({key,value})=>localStorage.setItem(key,value),savedContext)
  await page.reload({waitUntil:'networkidle'});await version(page,1)
  steps.push('missing browser context blocks real-mode writes without simulation fallback')

  await page.getByTestId('open-signal').click();await page.getByTestId('signal-delay').click()
  await page.getByRole('status').filter({hasText:'未核实异常会阻止确认'}).waitFor()
  assert.equal(await page.getByTestId('confirm-draft').count(),0)
  steps.push('unverified user event blocks confirmation')
  await verifyFixtureEvent(page)
  await shot(page,'03-controlled-delay-drafts')
  await page.getByTestId('confirm-draft').first().click();await version(page,2)
  await page.reload({waitUntil:'networkidle'});await version(page,2)
  steps.push('controlled event verification -> candidates -> confirm V2 -> refresh restores')
  await page.getByTestId('open-signal').click();await page.getByTestId('signal-closure').click()
  await page.getByRole('status').filter({hasText:'未核实异常会阻止确认'}).waitFor()
  await verifyFixtureEvent(page)
  await page.getByTestId('confirm-draft').first().click();await version(page,3)
  await page.getByTestId('open-history').click();await page.getByTestId('history-drawer').waitFor()
  await shot(page,'04-controlled-version-history')
  await page.keyboard.press('Escape')
  await page.getByTestId('theme-toggle').click()
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light')
  await shot(page,'05-console-light')
  await page.setViewportSize({width:390,height:844})
  await page.getByTestId('recommendations').scrollIntoViewIfNeeded()
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
  await shot(page,'06-mobile')
  steps.push('closure replacement/drop -> confirm V3 -> version history -> light/mobile layout')
  // Existing offline simulation remains available to automated tests with clear labels.
  const mock=await context.newPage();await mock.goto(`${base}?mode=mock`)
  await mock.getByTestId('create-trip').click();await version(mock,1)
  await mock.getByTestId('open-signal').click();await mock.getByTestId('signal-delay').click()
  await mock.getByTestId('decision-dock').waitFor();await mock.getByTestId('confirm-draft').first().click();await version(mock,2)
  steps.push('explicit mock mode regression (not a live service substitute)')
  // Actual providers: use the normal local service, not the fixture server.
  if(process.env.E2E_SKIP_LIVE!=='1'){
    const live=await browser.newContext({baseURL:liveBase,locale:'zh-CN',timezoneId:'Asia/Shanghai',viewport:{width:1440,height:960}})
    const livePage=await live.newPage();livePage.setDefaultTimeout(180000)
    livePage.on('pageerror',e=>errors.push(`live: ${e}`))
    await livePage.goto(liveBase,{waitUntil:'networkidle'})
    await fill(livePage)
    await livePage.getByTestId('create-trip').click()
    await livePage.getByTestId('recommendation-card').first().waitFor()
    assert.equal(await livePage.getByTestId('recommendation-card').count(),3)
    assert.match(await livePage.getByTestId('recommendations').innerText(),/真实来源/)
    assert.equal(await livePage.getByTestId('save-recommendation').isDisabled(),true)
    await livePage.getByTestId('recommendations').evaluate(el=>el.scrollIntoView({block:'start'}))
    await shot(livePage,'07-live-hangzhou-map-weather')
    const firstText=await livePage.getByTestId('recommendation-itinerary').innerText()
    assert.match(firstText,/杭州|西湖|浙江/)
    await livePage.getByTestId('field-city').fill('南京')
    await livePage.getByTestId('create-trip').click()
    await livePage.getByRole('button',{name:'生成路线推荐',exact:true}).waitFor()
    await livePage.waitForFunction(()=>document.querySelector('[data-testid="recommendations"]')?.textContent?.includes('上海 → 南京'))
    assert.match(await livePage.getByTestId('recommendation-itinerary').innerText(),/南京|江苏|中山/)
    await livePage.getByTestId('recommendations').evaluate(el=>el.scrollIntoView({block:'start'}))
    await shot(livePage,'08-live-nanjing-map-weather')
    steps.push('live providers: Hangzhou + Nanjing change actual POIs/routes/weather; incomplete rules block V1')
    await live.close()
  }
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({status:'PASS',steps,pageErrors:errors,screenshots:shots},null,2))
} finally {
  if(browser) await browser.close()
  for(const child of children.reverse()) if(child.exitCode===null) child.kill()
}
