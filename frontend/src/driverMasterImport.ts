import type { DriverImportRow } from './types'

const fields = {
  'STATUS':'status','DATA DO CADASTRO':'registration_date','MOTORISTA':'name',
  'TELEFONE PRINCIPAL':'primary_phone','TELEFONE DE EMERGENCIA':'emergency_phone',
  'CPF':'cpf','CLIENTE OPERACAO':'client_operation','ROTAS':'routes','PERFIL DE VEICULO':'vehicle_profile',
} as const

export function normalizeDriverHeader(value:unknown){return String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().replace(/\s*\/\s*/g,' ').replace(/\s+/g,' ').trim()}
const text=(value:unknown)=>String(value??'').trim()
function dateOnly(value:unknown):{value?:string;warning?:string}{
 if(value==null||value==='')return {warning:'Data do cadastro não informada'}
 if(typeof value==='number'){
  const parsed=new Date(Date.UTC(1899,11,30)+Math.floor(value)*86400000)
  if(Number.isFinite(parsed.getTime()))return {value:parsed.toISOString().slice(0,10)}
 }
 const raw=text(value),br=raw.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})/),iso=raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
 const result=br?`${br[3]}-${br[2].padStart(2,'0')}-${br[1].padStart(2,'0')}`:iso?iso[0]:''
 return result?{value:result}:{warning:'Data do cadastro inválida'}
}
export function parseDriverMatrix(matrix:unknown[][]):DriverImportRow[]{
 const headerIndex=matrix.findIndex(row=>row.some(cell=>normalizeDriverHeader(cell)==='MOTORISTA'))
 if(headerIndex<0)throw new Error('Cabeçalho MOTORISTA não encontrado.')
 const indexes=new Map<string,number>();matrix[headerIndex].forEach((cell,index)=>indexes.set(normalizeDriverHeader(cell),index))
 const missing=Object.keys(fields).filter(header=>!indexes.has(header));if(missing.length)throw new Error(`Colunas obrigatórias ausentes: ${missing.join(', ')}.`)
 const pick=(row:unknown[],header:keyof typeof fields)=>row[indexes.get(header)!]
 return matrix.slice(headerIndex+1).map((row,offset)=>({row,source_row:headerIndex+offset+2})).filter(({row})=>row.some(cell=>text(cell))).map(({row,source_row})=>{
  const parsedDate=dateOnly(pick(row,'DATA DO CADASTRO')),cpf=text(pick(row,'CPF')).replace(/\D/g,''),warnings:string[]=[]
  if(parsedDate.warning)warnings.push(parsedDate.warning);if(!cpf)warnings.push('CPF não informado');if(!text(pick(row,'TELEFONE PRINCIPAL')))warnings.push('Telefone principal não informado');if(!text(pick(row,'PERFIL DE VEICULO')))warnings.push('Perfil de veículo não informado')
  return {source_row,status:text(pick(row,'STATUS')),registration_date:parsedDate.value,name:text(pick(row,'MOTORISTA')),primary_phone:text(pick(row,'TELEFONE PRINCIPAL')),emergency_phone:text(pick(row,'TELEFONE DE EMERGENCIA')),cpf,client_operation:text(pick(row,'CLIENTE OPERACAO')),routes:text(pick(row,'ROTAS'))?[text(pick(row,'ROTAS'))]:[],vehicle_profile:text(pick(row,'PERFIL DE VEICULO')),warnings}
 })
}
export async function parseDriverFile(file:File):Promise<DriverImportRow[]>{
 const {read,utils}=await import('xlsx'),isCsv=file.name.toLowerCase().endsWith('.csv'),source=isCsv?await file.text():await file.arrayBuffer(),separator=isCsv&&String(source).split(/\r?\n/,1)[0].split(';').length>String(source).split(/\r?\n/,1)[0].split(',').length?';':','
 const workbook=read(source,isCsv?{type:'string',raw:true,FS:separator}:{type:'array',raw:true}),sheet=workbook.Sheets[workbook.SheetNames[0]]
 return parseDriverMatrix(utils.sheet_to_json<unknown[]>(sheet,{header:1,raw:true,defval:null}))
}
