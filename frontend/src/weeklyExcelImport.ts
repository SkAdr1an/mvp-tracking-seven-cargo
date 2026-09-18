import type { CellObject, WorkBook, WorkSheet } from 'xlsx'
import { classifyWeeklyProgramming, type WeeklyProgrammingRow, type WeeklyProgrammingStatus } from './weeklyProgramming.ts'

export type HeaderKey = 'lt'|'vehicle'|'driver'|'origin'|'destination'|'etaOrigin'|'etaDestination'|'truck'|'trailer'|'phone'|'cpf'|'email'
export type DuplicatePolicy = 'first'|'last'

export interface ImportIssue { row:number; message:string }
export interface ParsedWeeklySheet {
  sheetName:string
  rows:WeeklyProgrammingRow[]
  recognizedCount:number
  validCount:number
  ignoredCount:number
  emptyCount:number
  invalidCount:number
  duplicateLts:string[]
  issues:ImportIssue[]
  stateCounts:Record<WeeklyProgrammingStatus,number>
}

export interface ExcelImportCandidate {
  fileName:string
  workbook:WorkBook
  weeklySheets:string[]
}

const REQUIRED:HeaderKey[]=['lt','vehicle','driver','origin','destination','etaOrigin']
const HEADER_SCAN_ROWS=60
const ALIASES:Record<HeaderKey,string[]>={
  lt:['LT','LH TRIP','NUMERO LT','N LT'],
  vehicle:['VEICULO','PERFIL VEICULO','TIPO VEICULO'],
  driver:['MOTORISTA','NOME MOTORISTA'],
  origin:['ORIGEM','LOCAL ORIGEM'],
  destination:['DESTINO','LOCAL DESTINO'],
  etaOrigin:['ETA ORIGEM','ETA DE ORIGEM','ETAORIGEM'],
  etaDestination:['ETA DESTINO','ETA DE DESTINO','ETADESTINO'],
  truck:['CAVALO','PLACA CAVALO'],
  trailer:['CARRETA','PLACA CARRETA'],
  phone:['TELEFONE','FONE','CELULAR'],
  cpf:['CPF','CPF MOTORISTA'],
  email:['EMAIL','E MAIL'],
}

const aliasLookup=new Map(Object.entries(ALIASES).flatMap(([key,values])=>values.map(value=>[normalizeHeader(value),key as HeaderKey])))

export function normalizeHeader(value:unknown):string{
  return String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[-_/]+/g,' ').replace(/\s+/g,' ').trim().toUpperCase()
}

export function normalizeWeeklySheetName(name:string):string|undefined{const match=name.trim().match(/^LHW[\s_-]*(\d{1,3})$/i);return match?`LHW${match[1]}`:undefined}
export function weeklySheetNames(names:string[]):string[]{return names.map(name=>name.trim()).filter(name=>Boolean(normalizeWeeklySheetName(name)))}

export async function readExcelFile(file:File):Promise<ExcelImportCandidate>{
  if(!/\.(xlsx|xls)$/i.test(file.name)) throw new Error('Selecione um arquivo Excel com extensão .xlsx ou .xls.')
  try{
    const {read}=await import('xlsx')
    const workbook=read(await file.arrayBuffer(),{type:'array',cellStyles:true,cellDates:false,cellNF:true,cellText:true,dense:false})
    const weeklySheets=weeklySheetNames(workbook.SheetNames)
    if(!weeklySheets.length) throw new Error('Não encontramos uma aba semanal válida neste arquivo.')
    return {fileName:file.name,workbook,weeklySheets}
  }catch(error){
    if(error instanceof Error&&error.message.startsWith('Não encontramos')) throw error
    if(error instanceof Error&&error.message.startsWith('Selecione')) throw error
    throw new Error('O arquivo não pôde ser lido. Verifique se ele é uma planilha Excel válida.')
  }
}

export async function parseWeeklyCsv(csv:string,sheetName:string,referenceTime=new Date(),rowColors:Record<string,string>={}):Promise<ParsedWeeklySheet>{
  const {read}=await import('xlsx')
  const workbook=read(csv,{type:'string',raw:true})
  const original=workbook.SheetNames[0]
  workbook.Sheets[sheetName]=workbook.Sheets[original]
  workbook.SheetNames=[sheetName]
  if(original!==sheetName)delete workbook.Sheets[original]
  const parsed=parseWeeklySheet(workbook,sheetName,referenceTime)
  parsed.rows=parsed.rows.map(row=>{
    const color=rowColors[String(row.sourceRow)]
    const sourceColor=color==='RED'||color==='GREEN'?color:'WHITE'
    const next={...row,sourceColor} as WeeklyProgrammingRow
    return {...next,status:classifyWeeklyProgramming(next,referenceTime)}
  })
  parsed.stateCounts=emptyStateCounts()
  for(const row of parsed.rows)parsed.stateCounts[row.status]++
  return parsed
}

export function parseWeeklySheet(workbook:WorkBook,sheetName:string,referenceTime=new Date()):ParsedWeeklySheet{
  const normalized=normalizeWeeklySheetName(sheetName)
  const actualName=workbook.SheetNames.find(name=>normalizeWeeklySheetName(name)===normalized)
  const sheet=actualName?workbook.Sheets[actualName]:undefined
  if(!sheet) throw new Error(`Não foi possível localizar os dados da ${normalized||sheetName.trim()} no arquivo.`)
  const range=decodeRange(sheet['!ref'])
  const header=findHeader(sheet,range)
  if(!header) throw new Error('Não foi possível localizar os cabeçalhos obrigatórios.')
  const rows:WeeklyProgrammingRow[]=[]
  const issues:ImportIssue[]=[]
  let ignoredCount=0
  let emptyCount=0
  for(let rowIndex=header.row+1;rowIndex<=range.endRow;rowIndex++){
    const cells=header.columns.map(column=>cellAt(sheet,rowIndex,column))
    if(cells.every(cell=>!cellValue(cell))){emptyCount++;continue}
    const etaOriginColumn=bestDateColumn(sheet,rowIndex,header.candidates.etaOrigin||[header.byKey.etaOrigin])
    const etaDestinationColumn=bestDateColumn(sheet,rowIndex,header.candidates.etaDestination||[header.byKey.etaDestination])
    const values=Object.fromEntries(Object.entries(header.byKey).map(([key,column])=>{
      const selected=key==='etaOrigin'?etaOriginColumn:key==='etaDestination'?etaDestinationColumn:column
      return [key,cellValue(cellAt(sheet,rowIndex,selected),key==='lt')]
    })) as Partial<Record<HeaderKey,string>>
    if(!values.lt&&!values.etaOrigin){ignoredCount++;continue}
    const missing=[]
    if(!values.lt)missing.push('LT')
    if(!values.etaOrigin)missing.push('ETA Origem')
    if(!values.origin)missing.push('origem')
    if(!values.destination)missing.push('destino')
    const etaOrigin=parseExcelDate(cellAt(sheet,rowIndex,etaOriginColumn))
    if(values.etaOrigin&&!etaOrigin)missing.push('ETA Origem inválida')
    if(missing.length){issues.push({row:rowIndex+1,message:`Campos obrigatórios: ${[...new Set(missing)].join(', ')}.`});continue}
    const importedStatus=recognizeStatus(cells,values)
    const sourceColor=detectSourceColor(cells)
    const programming:WeeklyProgrammingRow={
      id:`import-${rowIndex+1}-${values.lt}`,
      week:normalized||sheetName.trim(),
      etaOrigin:etaOrigin!,
      etaDestination:parseExcelDate(cellAt(sheet,rowIndex,etaDestinationColumn)),
      origin:values.origin!,destination:values.destination!,vehicleProfile:values.vehicle||'',lt:values.lt!,driver:values.driver||undefined,
      truck:values.truck||undefined,trailer:values.trailer||undefined,phone:values.phone||undefined,cpf:values.cpf||undefined,email:values.email||undefined,
      sourceColor,importedStatusText:statusText(cells),status:importedStatus||'OPEN',pending:[],sourceRow:rowIndex+1,
    }
    programming.status=classifyWeeklyProgramming(programming,referenceTime)
    rows.push(programming)
  }
  const occurrences=new Map<string,number>()
  for(const row of rows)occurrences.set(normalizeLt(row.lt),(occurrences.get(normalizeLt(row.lt))||0)+1)
  const duplicateLts=[...occurrences].filter(([,count])=>count>1).map(([lt])=>lt)
  const stateCounts=emptyStateCounts()
  for(const row of rows)stateCounts[row.status]++
  return {sheetName:normalized||sheetName.trim(),rows,recognizedCount:rows.length+issues.length,validCount:rows.length,ignoredCount,emptyCount,invalidCount:issues.length,duplicateLts,issues,stateCounts}
}

export function deduplicateRows(rows:WeeklyProgrammingRow[],policy:DuplicatePolicy):WeeklyProgrammingRow[]{
  const selected=new Map<string,WeeklyProgrammingRow>()
  const source=policy==='last'?rows:[...rows].reverse()
  for(const row of source)selected.set(normalizeLt(row.lt),row)
  return [...selected.values()].sort((a,b)=>(a.sourceRow??0)-(b.sourceRow??0))
}

export function parseExcelDate(cell:CellObject|undefined):string|undefined{
  if(!cell||cell.v===null||cell.v===undefined||cell.v==='')return undefined
  if(cell.v instanceof Date&&!Number.isNaN(cell.v.getTime()))return localParts(cell.v.getFullYear(),cell.v.getMonth()+1,cell.v.getDate(),cell.v.getHours(),cell.v.getMinutes(),cell.v.getSeconds())
  if(typeof cell.v==='number')return serialDate(cell.v)
  const text=String(cell.v).trim()
  let match=text.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})(?:\s+(\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?)?$/)
  if(match){const year=Number(match[3])+(match[3].length===2?(Number(match[3])>=70?1900:2000):0);return validLocal(year,Number(match[2]),Number(match[1]),Number(match[4]||0),Number(match[5]||0),Number(match[6]||0))}
  match=text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?)?$/)
  if(match)return validLocal(Number(match[1]),Number(match[2]),Number(match[3]),Number(match[4]||0),Number(match[5]||0),Number(match[6]||0))
  return undefined
}

function serialDate(serial:number):string|undefined{
  if(!Number.isFinite(serial)||serial<=0)return undefined
  const whole=Math.floor(serial)
  const adjusted=whole>59?whole-1:whole
  const base=Date.UTC(1899,11,31)
  const date=new Date(base+adjusted*86400000)
  let seconds=Math.round((serial-whole)*86400)
  if(seconds>=86400){seconds=0;date.setUTCDate(date.getUTCDate()+1)}
  return localParts(date.getUTCFullYear(),date.getUTCMonth()+1,date.getUTCDate(),Math.floor(seconds/3600),Math.floor(seconds%3600/60),seconds%60)
}

function validLocal(year:number,month:number,day:number,hour:number,minute:number,second:number):string|undefined{
  const candidate=new Date(year,month-1,day,hour,minute,second)
  if(candidate.getFullYear()!==year||candidate.getMonth()!==month-1||candidate.getDate()!==day||candidate.getHours()!==hour||candidate.getMinutes()!==minute)return undefined
  return localParts(year,month,day,hour,minute,second)
}

function localParts(year:number,month:number,day:number,hour:number,minute:number,second:number):string{
  const pad=(value:number)=>String(value).padStart(2,'0')
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:${pad(second)}`
}

function recognizeStatus(cells:(CellObject|undefined)[],values:Partial<Record<HeaderKey,string>>):WeeklyProgrammingStatus|undefined{
  const text=normalizeHeader([...Object.values(values),...cells.map(cell=>cellValue(cell))].join(' '))
  if(/CANCELAD[AO]/.test(text))return 'CANCELLED'
  if(/NO\s*SHOW|NOSHOW|NAO EXECUTADA/.test(text))return 'NOSHOW'
  return undefined
}

function statusText(cells:(CellObject|undefined)[]):string|undefined{return cells.map(cell=>cellValue(cell)).find(value=>/^(?:CANCELAD[AO]|NO\s*SHOW|NOSHOW|NÃO EXECUTADA|NAO EXECUTADA)$/i.test(value))}

function detectSourceColor(cells:(CellObject|undefined)[]):'RED'|'GREEN'|'WHITE'{
  let green=false
  for(const cell of cells){
    const rgb=String((cell?.s as {fill?:{fgColor?:{rgb?:string}}}|undefined)?.fill?.fgColor?.rgb||'').replace(/^FF/i,'').toUpperCase()
    if(/^(?:FF0000|EA4335|D93025)$/.test(rgb))return 'RED'
    if(/^(?:00FF00|00B050|34A853)$/.test(rgb))green=true
  }
  return green?'GREEN':'WHITE'
}

function findHeader(sheet:WorkSheet,range:{startRow:number;endRow:number;startColumn:number;endColumn:number}){
  for(let row=range.startRow;row<=Math.min(range.endRow,range.startRow+HEADER_SCAN_ROWS-1);row++){
    const byKey={} as Partial<Record<HeaderKey,number>>
    const candidates={} as Partial<Record<HeaderKey,number[]>>
    const columns=[]
    for(let column=range.startColumn;column<=range.endColumn;column++){
      columns.push(column)
      const key=aliasLookup.get(normalizeHeader(cellValue(cellAt(sheet,row,column))))
      if(key){(candidates[key]??=[]).push(column);if(byKey[key]===undefined)byKey[key]=column}
    }
    if(REQUIRED.every(key=>byKey[key]!==undefined))return {row,columns,byKey:byKey as Record<HeaderKey,number>,candidates}
  }
  return undefined
}

function bestDateColumn(sheet:WorkSheet,row:number,columns:(number|undefined)[]):number|undefined{
  let selected: number|undefined
  let selectedPrecision=-1
  for(const column of columns){
    if(column===undefined)continue
    const cell=cellAt(sheet,row,column)
    if(!parseExcelDate(cell))continue
    const precision=datePrecision(cell)
    if(precision>=selectedPrecision){selected=column;selectedPrecision=precision}
  }
  return selected??columns.find(column=>column!==undefined)
}

function datePrecision(cell:CellObject|undefined):number{
  if(!cell)return -1
  if(cell.v instanceof Date)return cell.v.getHours()||cell.v.getMinutes()||cell.v.getSeconds()?2:1
  if(typeof cell.v==='number')return Math.abs(cell.v-Math.trunc(cell.v))>1e-9?2:1
  return /(?:\s|T)\d{1,2}:\d{2}/.test(String(cell.v??'').trim())?2:1
}

function decodeRange(reference:string|undefined){
  if(!reference)return {startRow:0,endRow:0,startColumn:0,endColumn:0}
  const match=reference.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/i)
  if(!match)return {startRow:0,endRow:0,startColumn:0,endColumn:0}
  return {startColumn:columnNumber(match[1]),startRow:Number(match[2])-1,endColumn:columnNumber(match[3]),endRow:Number(match[4])-1}
}
function columnNumber(letters:string){return [...letters.toUpperCase()].reduce((total,char)=>total*26+char.charCodeAt(0)-64,0)-1}
function cellAt(sheet:WorkSheet,row:number,column:number|undefined):CellObject|undefined{return column===undefined?undefined:sheet[`${columnName(column)}${row+1}`] as CellObject|undefined}
function columnName(column:number){let value=column+1,result='';while(value){const remainder=(value-1)%26;result=String.fromCharCode(65+remainder)+result;value=Math.floor((value-1)/26)}return result}
function cellValue(cell:CellObject|undefined,preferFormatted=false):string{
  if(!cell)return ''
  if(preferFormatted&&cell.w)return expandScientific(cell.w.trim(),cell.v)
  if(cell.v===null||cell.v===undefined)return ''
  return String(cell.v).replace(/\s+/g,' ').trim()
}
function expandScientific(formatted:string,raw:unknown){return /e[+-]?\d+/i.test(formatted)&&typeof raw==='number'?raw.toLocaleString('fullwide',{useGrouping:false,maximumSignificantDigits:21}):formatted}
function normalizeLt(value:string){return value.replace(/\s+/g,' ').trim().toUpperCase()}
function emptyStateCounts():Record<WeeklyProgrammingStatus,number>{return {EMERGENCY:0,OPEN:0,SUPERVISION:0,AWAITING_CONFIRMATION:0,PAYMENT_ORDER:0,PAYMENT:0,COMPLETED:0,CANCELLED:0,NOSHOW:0}}
