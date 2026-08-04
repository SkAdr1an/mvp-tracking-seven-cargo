const endpoint = await fetch('http://127.0.0.1:9222/json/new?http://localhost:5173', { method: 'PUT' }).then((response) => response.json())
const socket = new WebSocket(endpoint.webSocketDebuggerUrl)
let nextId = 0
const pending = new Map()
const exceptions = []
socket.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data)
  if (message.id && pending.has(message.id)) {
    const request = pending.get(message.id)
    pending.delete(message.id)
    message.error ? request.reject(new Error(message.error.message)) : request.resolve(message.result)
  } else if (message.method === 'Runtime.exceptionThrown') {
    exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text)
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
  const response = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text)
  return response.result.value
}
await Promise.all([send('Page.enable'), send('Runtime.enable')])
await send('Page.navigate', { url: 'http://localhost:5173/' })
await new Promise((resolve) => setTimeout(resolve, 3000))
const counts = () => evaluate(`({
  sites: document.querySelectorAll('.map-symbol--site').length,
  entry: document.querySelectorAll('.site-radius--entry').length,
  exit: document.querySelectorAll('.site-radius--exit').length,
  approach: document.querySelectorAll('.site-radius--approach').length,
  trucks: document.querySelectorAll('.leaflet-interactive').length,
  recovery: !!document.querySelector('.content-error'),
})`)
const initial = await counts()
await evaluate(`([...document.querySelectorAll('#operational-map-filters button')].find((button) => button.textContent === 'Raios dos CDs')).click()`)
await new Promise((resolve) => setTimeout(resolve, 300))
const hidden = await counts()
await evaluate(`([...document.querySelectorAll('#operational-map-filters button')].find((button) => button.textContent === 'Raios dos CDs')).click()`)
await new Promise((resolve) => setTimeout(resolve, 300))
const restored = await counts()
const layouts = []
for (const width of [390, 768, 1440]) {
  await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 })
  await new Promise((resolve) => setTimeout(resolve, 150))
  layouts.push(await evaluate(`({width:innerWidth,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,map:!!document.querySelector('.operational-map')})`))
}
console.log(JSON.stringify({ initial, hidden, restored, layouts, exceptions }, null, 2))
socket.close()
