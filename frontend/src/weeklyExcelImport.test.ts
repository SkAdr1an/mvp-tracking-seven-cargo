import assert from 'node:assert/strict'
import test from 'node:test'
import type { CellObject, WorkBook, WorkSheet } from 'xlsx'
import { deduplicateRows, normalizeHeader, parseExcelDate, parseWeeklySheet, weeklySheetNames } from './weeklyExcelImport.ts'

const HEADERS=[' LT ','VEÍCULO',' MOTORISTA\n','ORIGEM','DESTINO','ETA ORIGEM','SITUAÇÃO','CAVALO','CARRETA']
const REFERENCE=new Date(2026,8,9,12,0,0)
const cell=(v:unknown,extra:Record<string,unknown>={}):CellObject=>({v,t:typeof v==='number'?'n':v instanceof Date?'d':'s',...extra} as CellObject)
function workbook(rows:Array<Array<CellObject|undefined>>,name=' LHW37 '):WorkBook{const sheet:WorkSheet={};rows.forEach((row,r)=>row.forEach((value,c)=>{if(value)sheet[`${String.fromCharCode(65+c)}${r+1}`]=value}));const last=String.fromCharCode(64+Math.max(...rows.map(row=>row.length)));sheet['!ref']=`A1:${last}${rows.length}`;return {SheetNames:[name],Sheets:{[name]:sheet}}}
const header=HEADERS.map(value=>cell(value))
const valid=(lt:CellObject=cell('LT-001'),eta:CellObject=cell('10/09/2026 14:30'),status?:CellObject)=>[lt,cell('Sider'),cell('Maria'),cell('Betim/MG'),cell('Contagem/MG'),eta,status,cell('ABC1D23'),cell('EFG4H56')]
test('reconhece LH Trip como identificador LT sem mapeamento permissivo',()=>{const lhHeaders=[...header];lhHeaders[0]=cell('LH Trip');const parsed=parseWeeklySheet(workbook([lhHeaders,valid()],' LHW38'),'LHW38',REFERENCE);assert.equal(parsed.rows[0].lt,'LT-001');assert.equal(parsed.sheetName,'LHW38')})

test('normaliza cabeçalhos com acentos, espaços e quebras',()=>assert.equal(normalizeHeader('  ETA\n ORÍGEM  '),'ETA ORIGEM'))
test('reconhece aba semanal mesmo com espaço externo',()=>assert.deepEqual(weeklySheetNames([' Resumo ',' LHW37 ','LHW_38']),['LHW37','LHW_38']))
test('localiza cabeçalho fora da primeira linha',()=>assert.equal(parseWeeklySheet(workbook([[cell('PROGRAMAÇÃO SEVEN7')],[],header,valid()]),'LHW37',REFERENCE).validCount,1))
test('interpreta data nativa sem deslocar o horário local',()=>assert.equal(parseExcelDate(cell(new Date(2026,8,10,14,30))),'2026-09-10T14:30:00'))
test('interpreta número serial do Excel',()=>assert.equal(parseExcelDate(cell(46275.5)),'2026-09-10T12:00:00'))
test('interpreta data brasileira em texto',()=>assert.equal(parseExcelDate(cell('10/09/2026 14:30')),'2026-09-10T14:30:00'))
test('preserva LT formatada como texto sem notação científica',()=>assert.equal(parseWeeklySheet(workbook([header,valid(cell(123456789012,{w:'000123456789012'}))]),'LHW37',REFERENCE).rows[0].lt,'000123456789012'))
test('detecta LT duplicada e aplica a escolha',()=>{const first=valid(cell('LT-X'));const last=valid(cell('LT-X'));last[3]=cell('Outra origem');const parsed=parseWeeklySheet(workbook([header,first,last]),'LHW37',REFERENCE);assert.deepEqual(parsed.duplicateLts,['LT-X']);assert.equal(deduplicateRows(parsed.rows,'first')[0].origin,'Betim/MG');assert.equal(deduplicateRows(parsed.rows,'last')[0].origin,'Outra origem')})
test('linha totalmente vazia não entra como ignorada',()=>{const parsed=parseWeeklySheet(workbook([header,[],valid()]),'LHW37',REFERENCE);assert.equal(parsed.emptyCount,1);assert.equal(parsed.ignoredCount,0);assert.equal(parsed.validCount,1)})
test('linha somente formatada não entra como ignorada',()=>{const formatted=Array.from({length:9},()=>cell('',{s:{fill:{fgColor:{rgb:'FF00B050'}}}}));const parsed=parseWeeklySheet(workbook([header,formatted,valid()]),'LHW37',REFERENCE);assert.equal(parsed.emptyCount,1);assert.equal(parsed.ignoredCount,0)})
test('motorista e veículo ausentes não invalidam',()=>{const data=valid();data[1]=undefined;data[2]=undefined;const parsed=parseWeeklySheet(workbook([header,data]),'LHW37',REFERENCE);assert.equal(parsed.validCount,1);assert.equal(parsed.rows[0].driver,undefined)})
test('status antigo fica registrado sem interferir no fluxo temporário',()=>{const parsed=parseWeeklySheet(workbook([header,valid(cell('LT-C'),cell('10/09/2026 14:30'),cell('Cancelada'))]),'LHW37',REFERENCE);assert.equal(parsed.rows[0].status,'AWAITING_CONFIRMATION');assert.equal(parsed.rows[0].importedStatusText,'Cancelada')})
test('NoShow e NÃO EXECUTADA são preservados apenas como informação original',()=>{for(const status of ['No Show','NÃO EXECUTADA']){const parsed=parseWeeklySheet(workbook([header,valid(cell(`LT-${status}`),cell('10/09/2026 14:30'),cell(status))]),'LHW37',REFERENCE);assert.equal(parsed.rows[0].status,'AWAITING_CONFIRMATION');assert.equal(parsed.rows[0].importedStatusText,status)}})
test('cor verde não decide o estado',()=>{const data=valid();data[0]=cell('LT-G',{s:{fill:{fgColor:{rgb:'FF00B050'}}}});assert.equal(parseWeeklySheet(workbook([header,data]),'LHW37',REFERENCE).rows[0].status,'AWAITING_CONFIRMATION')})
test('linha vermelha entra como cancelada',()=>{const data=valid();data[0]=cell('LT-R',{s:{fill:{fgColor:{rgb:'FFFF0000'}}}});const parsed=parseWeeklySheet(workbook([header,data]),'LHW37',REFERENCE).rows[0];assert.equal(parsed.sourceColor,'RED');assert.equal(parsed.status,'CANCELLED')})
test('ETA inválida entra como erro',()=>{const parsed=parseWeeklySheet(workbook([header,valid(cell('LT-I'),cell('data desconhecida'))]),'LHW37',REFERENCE);assert.equal(parsed.invalidCount,1);assert.equal(parsed.validCount,0)})
test('ETA duplicada prioriza por linha a coluna com data e hora completas',()=>{const duplicateHeaders=[...header,cell('ETA ORIGEM'),cell('ETA DESTINO')];const data=valid(cell('LT-DUP'),cell('17/09/2026'));data.push(cell('17/09/2026 02:00'),cell('18/09/2026 09:00'));const parsed=parseWeeklySheet(workbook([duplicateHeaders,data],'LHW38'),'LHW38',REFERENCE);assert.equal(parsed.rows[0].etaOrigin,'2026-09-17T02:00:00');assert.equal(parsed.rows[0].etaDestination,'2026-09-18T09:00:00')})
test('ETA duplicada mantém a primeira quando apenas ela possui horário',()=>{const duplicateHeaders=[...header,cell('ETA ORIGEM')];const data=valid(cell('LT-DUP-2'),cell('17/09/2026 03:30'));data.push(cell('17/09/2026'));const parsed=parseWeeklySheet(workbook([duplicateHeaders,data],'LHW38'),'LHW38',REFERENCE);assert.equal(parsed.rows[0].etaOrigin,'2026-09-17T03:30:00')})
