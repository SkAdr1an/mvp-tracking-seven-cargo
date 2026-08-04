import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const component = readFileSync(new URL('./PortalAlerts.tsx', import.meta.url), 'utf8')
const hook = readFileSync(new URL('./hooks/usePortalAlerts.ts', import.meta.url), 'utf8')
const api = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')

test('portal alerts use only the token-scoped endpoint and poll without push', () => { assert.match(api, /public\/trips\/\$\{encodeURIComponent\(token\)\}\/alerts/); assert.match(hook, /60_000/); assert.doesNotMatch(`${component}${hook}`, /Notification|PushManager|serviceWorker/) })
test('alerts expose distance, source, age, safe guidance and degraded integrations', () => { assert.match(component, /aprox\./); assert.match(component, /alert\.source/); assert.match(component, /locationAgeLabel/); assert.match(component, /alert\.guidance/); assert.match(component, /informações de trânsito ou clima está indisponível/); assert.doesNotMatch(component, /posto|homologad/i) })
