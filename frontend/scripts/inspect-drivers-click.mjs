const endpoint = await fetch('http://127.0.0.1:9222/json/new?http://localhost:5173', { method: 'PUT' }).then((response) => response.json())
const socket = new WebSocket(endpoint.webSocketDebuggerUrl)
let nextId = 0
const pending = new Map()
const events = []

socket.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data)
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id)
    pending.delete(message.id)
    message.error ? reject(new Error(message.error.message)) : resolve(message.result)
  } else if (message.method) {
    events.push(message)
  }
})

await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

function send(method, params = {}) {
  const id = ++nextId
  socket.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) {
    throw new Error(`${result.exceptionDetails.text}: ${result.exceptionDetails.exception?.description || ''}`)
  }
  return result.result.value
}

await Promise.all([
  send('Page.enable'),
  send('Runtime.enable'),
  send('Log.enable'),
  send('Network.enable'),
])
await send('Page.navigate', { url: 'http://localhost:5173/' })
await new Promise((resolve) => setTimeout(resolve, 2500))

const before = await evaluate(`(() => {
  const button = [...document.querySelectorAll('button')].find((element) => element.textContent.includes('Motoristas'))
  const ancestry = []
  for (let element = button; element; element = element.parentElement) {
    ancestry.push({
      tag: element.tagName,
      type: element.getAttribute('type'),
      href: element.getAttribute('href'),
      target: element.getAttribute('target'),
      role: element.getAttribute('role'),
      onclick: element.getAttribute('onclick'),
    })
  }
  return { url: location.href, button: button?.outerHTML, ancestry, sidebar: !!document.querySelector('.sidebar'), topbar: !!document.querySelector('.topbar') }
})()`)
const targetsBefore = await fetch('http://127.0.0.1:9222/json/list').then((response) => response.json())
if (!before.button) {
  const body = await evaluate(`document.body.innerHTML`)
  console.log(JSON.stringify({ before, body, events }, null, 2))
  socket.close()
  process.exit(2)
}
await evaluate(`document.querySelectorAll('.nav__item')[1].click()`)
await new Promise((resolve) => setTimeout(resolve, 1500))
const after = await evaluate(`({
  url: location.href,
  title: document.querySelector('.topbar h1')?.textContent,
  sidebar: !!document.querySelector('.sidebar'),
  topbar: !!document.querySelector('.topbar'),
  drivers: !!document.querySelector('.drivers-page'),
  driverRows: document.querySelectorAll('.driver-card').length,
  controls: document.querySelectorAll('.management-actions button').length,
})`)
const controls = await evaluate(`(async () => {
  const firstRow = document.querySelector('.driver-card')
  const pin = firstRow?.querySelector('.management-actions button:first-child')
  const hide = firstRow?.querySelector('.management-actions button:last-child')
  if (!firstRow || !pin || !hide) return { tested: false }
  const driverId = pin.getAttribute('aria-label')?.replace(/^Fixar /, '').replace(/ no monitoramento$/, '')
  pin.click()
  await new Promise((resolve) => setTimeout(resolve, 100))
  const pinned = pin.getAttribute('aria-pressed') === 'true'
  hide.click()
  await new Promise((resolve) => setTimeout(resolve, 100))
  const hidden = ![...document.querySelectorAll('.driver-card')].some((row) => row.querySelector('.management-actions button')?.getAttribute('aria-label')?.includes(driverId))
  return { tested: true, driverId, pinned, hidden, storedHidden: localStorage.getItem('seven-hidden-drivers') }
})()`)
await evaluate(`document.querySelectorAll('.nav__item')[0].click()`)
await new Promise((resolve) => setTimeout(resolve, 500))
const returned = await evaluate(`({
  url: location.href,
  sidebar: !!document.querySelector('.sidebar'),
  topbar: !!document.querySelector('.topbar'),
  overview: !!document.querySelector('.overview-page, .overview-grid, .map-shell'),
})`)
const targetsAfter = await fetch('http://127.0.0.1:9222/json/list').then((response) => response.json())
const relevantEvents = events.filter(({ method, params }) =>
  ['Runtime.exceptionThrown', 'Log.entryAdded', 'Page.frameNavigated'].includes(method) ||
  (method === 'Network.requestWillBeSent' && params.type === 'Document'),
)
console.log(JSON.stringify({
  before,
  after,
  controls,
  returned,
  pageTargetsBefore: targetsBefore.filter(({ type }) => type === 'page').map(({ id, url }) => ({ id, url })),
  pageTargetsAfter: targetsAfter.filter(({ type }) => type === 'page').map(({ id, url }) => ({ id, url })),
  events: relevantEvents,
}, null, 2))
socket.close()
