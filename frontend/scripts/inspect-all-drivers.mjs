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

await Promise.all([send('Page.enable'), send('Runtime.enable'), send('Network.enable')])
await send('Network.setCacheDisabled', { cacheDisabled: true })
await send('Page.navigate', { url: 'http://localhost:5173/' })
await new Promise((resolve) => setTimeout(resolve, 2500))
await evaluate(`localStorage.removeItem('seven-hidden-drivers')`)
await send('Page.reload', { ignoreCache: true })
await new Promise((resolve) => setTimeout(resolve, 1800))
await evaluate(`document.querySelectorAll('.nav__item')[1].click()`)
await new Promise((resolve) => setTimeout(resolve, 700))

const drivers = await evaluate(`[...document.querySelectorAll('.driver-open')].map((button) => button.getAttribute('aria-label'))`)
const results = []
for (let index = 0; index < drivers.length; index += 1) {
  const exceptionStart = exceptions.length
  await evaluate(`document.querySelectorAll('.driver-open')[${index}].click()`)
  await new Promise((resolve) => setTimeout(resolve, 250))
  results.push(await evaluate(`({
    driver: document.querySelectorAll('.driver-open')[${index}]?.getAttribute('aria-label'),
    shell: !!document.querySelector('.sidebar') && !!document.querySelector('.topbar'),
    list: !!document.querySelector('.drivers-page'),
    detail: !!document.querySelector('.driver-diagnostic'),
    recovery: !!document.querySelector('.content-error'),
  })`))
  results.at(-1).exceptions = exceptions.slice(exceptionStart)
}

for (const width of [390, 768, 1440]) {
  await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 })
  await new Promise((resolve) => setTimeout(resolve, 100))
  const layout = await evaluate(`({
    width: innerWidth,
    bodyOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    shell: !!document.querySelector('.sidebar') && !!document.querySelector('.topbar'),
    list: !!document.querySelector('.drivers-page'),
  })`)
  results.push({ layout })
}

console.log(JSON.stringify({
  url: await evaluate('location.href'),
  driverCount: drivers.length,
  results,
  exceptions,
}, null, 2))
socket.close()
