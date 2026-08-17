import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const history=readFileSync(new URL('./pages/DriverHistory.tsx',import.meta.url),'utf8')
const pending=readFileSync(new URL('./pages/PendingEvaluations.tsx',import.meta.url),'utf8')
const sidebar=readFileSync(new URL('./components/Sidebar.tsx',import.meta.url),'utf8')
const api=readFileSync(new URL('./api.ts',import.meta.url),'utf8')
const header=readFileSync(new URL('./components/Header.tsx',import.meta.url),'utf8')

test('driver history uses internal authenticated endpoints and stable identity',()=>{
  assert.match(history,/ID interno ou CPF/)
  assert.match(api,/panelRequest<Paged<DriverHistorySummary>>/)
  assert.doesNotMatch(history,/TrafegusClient|activeFleet\(/)
})
test('history exposes filters, pagination-ready API and on-demand PDF',()=>{
  for(const label of ['Início','Fim','Rota','Cliente','Status'])assert.match(history,new RegExp(label))
  assert.match(history,/Baixar relatório em PDF/)
  assert.match(api,/driverReport:/)
  assert.match(api,/response\.blob\(\)/)
  assert.match(api,/credentials: 'include'/)
  assert.doesNotMatch(api,/driverReportUrl/)
  assert.match(history,/disabled=\{reportLoading\}/)
  assert.match(history,/URL\.createObjectURL\(blob\)/)
  assert.match(history,/trip\.source_created_at/)
  assert.match(history,/Não disponível/)
  assert.doesNotMatch(history,/report\.json/)
})
test('pending evaluations are a dedicated sidebar page with complete form',()=>{
  assert.match(sidebar,/Avaliações pendentes/)
  for(const label of ['Comunicação','Cumprimento dos procedimentos','Colaboração com tracking','Uso do Time Mark','Comportamento profissional','Recomendação','Justificativa','Observação interna'])assert.match(pending,new RegExp(label))
  assert.match(pending,/Somente vencidas/)
})
test('history pages remain responsive without external navigation',()=>{
  assert.doesNotMatch(sidebar,/<a(?:\s|>)/)
  assert.match(history,/history-layout/)
  assert.match(pending,/pending-layout/)
})
test('empty and unavailable states never expose raw Not Found',()=>{
  assert.match(history,/Nenhum motorista consolidado até o momento/)
  assert.match(history,/Página \{page\} de \{totalPages\}/)
  assert.match(history,/setPage\(value=>Math\.min\(totalPages,value\+1\)\)/)
  assert.match(history,/Histórico indisponível\. Verifique se a API está em execução/)
  assert.doesNotMatch(history,/setError\(reason\.message\)/)
})
test('administrative API connection has explicit connected and unavailable states',()=>{
  assert.match(header,/apiMode\?'Conectado':'Tempo real'/)
  assert.match(header,/API indisponível/)
})
