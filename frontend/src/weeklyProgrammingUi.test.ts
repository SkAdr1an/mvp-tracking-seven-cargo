import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

const page=readFileSync(new URL('./pages/WeeklyProgramming.tsx',import.meta.url),'utf8')
const css=readFileSync(new URL('./weekly-programming.css',import.meta.url),'utf8')

test('exibe somente os três painéis do fluxo temporário',()=>{
  assert.equal((page.match(/<Hero /g)||[]).length,3)
  for(const title of ['EMERGÊNCIA','EM ABERTO','PROGRAMADA'])assert.match(page,new RegExp(`title="${title}"`))
  for(const hidden of ['title="SUPERVISÃO"','title="ORDEM DE PAGAMENTO"','title="PAGAMENTO"'])assert.doesNotMatch(page,new RegExp(hidden))
})
test('rotas vencidas são removidas da visualização',()=>assert.match(page,/isCurrentWeeklyProgramming\(row,now\)/))
test('painéis navegam até suas três seções',()=>{for(const state of ['EMERGENCY','OPEN','AWAITING_CONFIRMATION'])assert.match(page,new RegExp(`goToSection\\('${state}'\\)`));assert.match(page,/scrollIntoView\(\{behavior:'smooth'/)})
test('cada seção pode ser recolhida independentemente',()=>{assert.match(page,/Record<SectionStatus,boolean>/);assert.match(page,/collapsed=\{collapsed\[status\]\}/);assert.match(page,/aria-expanded=\{!collapsed\}/)})
test('captador pode preencher motorista e composição nas rotas incompletas',()=>{assert.match(page,/DriverEditor/);assert.match(page,/OperationalComposition/);assert.match(page,/Salvar alterações/);assert.match(page,/setSelectedDriver/);assert.match(page,/setManualComposition/)})
test('programada não exibe ações congeladas de supervisão ou pagamento',()=>{assert.doesNotMatch(page,/tone==='SUPERVISION'&&<SupervisionActions/);assert.doesNotMatch(page,/PaymentFlowActions row=/);assert.doesNotMatch(page,/Retornar para Supervisão/)})
test('resumo preserva os dados operacionais',()=>{for(const token of ['weeklyDateParts','presentWeeklyLocation','row.lt','row.vehicleProfile','row.driver'])assert.match(page,new RegExp(token.replace('.','\\.')))})
test('sincronização automática ocorre a cada minuto',()=>assert.match(page,/setInterval\(\(\)=>void syncOnline\(\),60_000\)/))
test('movimento respeita acessibilidade e página oculta',()=>{assert.match(page,/document\.hidden/);assert.match(page,/prefers-reduced-motion: reduce/);assert.match(css,/@media\(prefers-reduced-motion:reduce\)/)})
test('layout permanece responsivo',()=>{assert.match(css,/\.weekly-heroes\{grid-template-columns:repeat\(3/);assert.match(css,/@media\(max-width:700px\)/)})
