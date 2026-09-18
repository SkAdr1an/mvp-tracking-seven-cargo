import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import type { CellObject, WorkBook, WorkSheet } from 'xlsx'
import { parseWeeklySheet } from './weeklyExcelImport.ts'
import { applyImportDecision, setManualDriver, type WeeklyProgrammingRow } from './weeklyProgramming.ts'

const page=readFileSync(new URL('./pages/WeeklyProgramming.tsx',import.meta.url),'utf8')
const base=(week:string,lt:string,origin:string):WeeklyProgrammingRow=>({id:`${week}-${lt}`,week,lt,origin,destination:'B',etaOrigin:'2026-09-15T10:00:00',vehicleProfile:'Sider',status:'OPEN',pending:[]})
function workbook(name:string):WorkBook{const values=[['LT','VEÍCULO','MOTORISTA','ORIGEM','DESTINO','ETA ORIGEM'],['LT-38','Sider','','A','B','15/09/2026 10:00']];const sheet:WorkSheet={};values.forEach((row,r)=>row.forEach((value,c)=>sheet[`${String.fromCharCode(65+c)}${r+1}`]={v:value,t:'s'} as CellObject));sheet['!ref']='A1:F2';return {SheetNames:[name],Sheets:{[name]:sheet}}}
test('LHW38 selecionada chega ao parser mesmo quando a aba varia em caixa e espaço',()=>{const parsed=parseWeeklySheet(workbook(' lhw 38 '),'LHW38',new Date(2026,8,14));assert.equal(parsed.sheetName,'LHW38');assert.equal(parsed.rows[0].week,'LHW38')})
test('LHW37 permanece isolada ao importar LHW38 com LT repetido',()=>{const old37=setManualDriver(base('LHW37','LT-X','Origem 37'),'Motorista 37'),old38=base('LHW38','LT-X','Antiga 38'),next38=base('LHW38','LT-X','Nova 38');const result=applyImportDecision([old37,old38],[next38],true);assert.equal(result.length,2);assert.equal(result.find(row=>row.week==='LHW37')?.driver,'Motorista 37');assert.equal(result.find(row=>row.week==='LHW38')?.origin,'Nova 38')})
test('handler usa escolha do modal, bloqueia duplo clique e só ativa após persistir',()=>{assert.match(page,/const selected=sheetChoice/);assert.match(page,/if\(!candidate\|\|!sheetChoice\|\|sheetImportingRef\.current\)return/);assert.match(page,/sheetImportingRef\.current=true/);assert.match(page,/await api\.saveWeeklyProgrammingState[\s\S]*setWeek\(parsed\.sheetName\)/);assert.match(page,/loading\?'Importando\.\.\.'/)})
test('falhas permanecem visíveis dentro do modal e preservam a tela anterior',()=>{assert.match(page,/weekly-modal-error/);assert.match(page,/setDialogError/);assert.match(page,/try\{const parsed=parseWeeklySheet/);assert.doesNotMatch(page,/setRows\(\[\]\)/)})
