export const EMERGENCY_WINDOW_HOURS = 36

export type WeeklyProgrammingStatus = 'EMERGENCY' | 'OPEN' | 'SUPERVISION' | 'AWAITING_CONFIRMATION' | 'PAYMENT_ORDER' | 'PAYMENT' | 'COMPLETED' | 'CANCELLED' | 'NOSHOW'
export type WeeklyPriority = WeeklyProgrammingStatus
export type SupervisionStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface WeeklyProgrammingRow {
  id:string; week:string; etaOrigin:string; origin:string; destination:string; vehicleProfile:string; lt:string
  driver?:string; truck?:string; trailer?:string; etaDestination?:string; phone?:string; cpf?:string; email?:string
  sourceRow?:number; sourceColor?:'RED'|'GREEN'|'WHITE'; importedStatusText?:string; status:WeeklyProgrammingStatus; pending:string[]
  driverId?:string|null; manualDriver?:string|null; manualDriverId?:string|null
  manualTruck?:string|null; manualTrailer?:string|null
  supervisionStatus?:SupervisionStatus; operationalReleased?:boolean
  supervisionUpdatedAt?:string; supervisionUpdatedBy?:string
  supervisionReturnReason?:string; supervisionReturnNote?:string
  workflowStage?:'PAYMENT_ORDER'|'PAYMENT'; actualStartedAt?:string; actualStartedBy?:string
  paymentOrderSentAt?:string; paymentOrderSentBy?:string; paymentConfirmedAt?:string; paymentConfirmedBy?:string
  agreedFreightValue?:number; advancePercentage?:number
}

const HOUR_MS=60*60*1000
const filled=(value:string|undefined)=>Boolean(value?.trim())
export function isValidBrazilianPlate(value:string|null|undefined):boolean{const plate=normalizeVehiclePlate(value);return Boolean(plate&&/^[A-Z]{3}(?:\d{4}|\d[A-Z]\d{2})$/.test(plate))}
export function vehiclePendingFields(row:WeeklyProgrammingRow):string[]{return [...(!filled(row.truck)?['Cavalo']:!isValidBrazilianPlate(row.truck)?['Cavalo inválido']:[]),...(!filled(row.trailer)?['Carreta']:!isValidBrazilianPlate(row.trailer)?['Carreta inválida']:[])]}
export function vehicleIsComplete(row:WeeklyProgrammingRow):boolean{return vehiclePendingFields(row).length===0}

export function classifyWeeklyProgramming(row:WeeklyProgrammingRow,referenceTime:Date):WeeklyProgrammingStatus{
  if(row.sourceColor==='RED')return 'CANCELLED'
  const driver=filled(row.driver)
  if(driver)return 'AWAITING_CONFIRMATION'
  return localDate(row.etaOrigin).getTime()-referenceTime.getTime()<=EMERGENCY_WINDOW_HOURS*HOUR_MS?'EMERGENCY':'OPEN'
}

export function isCurrentWeeklyProgramming(row:WeeklyProgrammingRow,referenceTime=new Date()):boolean{
  return localDate(row.etaOrigin).getTime()>=referenceTime.getTime()
}

export function priorityFor(row:WeeklyProgrammingRow,referenceTime=new Date()):WeeklyPriority{return classifyWeeklyProgramming(row,referenceTime)}
export function chronological(rows:WeeklyProgrammingRow[]):WeeklyProgrammingRow[]{return [...rows].sort((a,b)=>localDate(a.etaOrigin).getTime()-localDate(b.etaOrigin).getTime())}
export function localDate(value:string):Date{const match=value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);return match?new Date(Number(match[1]),Number(match[2])-1,Number(match[3]),Number(match[4]),Number(match[5]),Number(match[6]||0)):new Date(value)}
export function applyImportDecision(current:WeeklyProgrammingRow[],candidate:WeeklyProgrammingRow[],confirmed:boolean):WeeklyProgrammingRow[]{
  if(!confirmed)return current
  const key=(row:WeeklyProgrammingRow)=>`${row.week.trim().toUpperCase()}::${row.lt.trim().toUpperCase()}`
  const currentByKey=new Map(current.map(row=>[key(row),row])),candidateWeeks=new Set(candidate.map(row=>row.week.trim().toUpperCase()))
  const untouched=current.filter(row=>!candidateWeeks.has(row.week.trim().toUpperCase()))
  return [...untouched,...candidate.map(row=>preserveManualDriver(currentByKey.get(key(row)),row))]
}

export function setManualDriver(row:WeeklyProgrammingRow,driver:string|null):WeeklyProgrammingRow{
  const value=driver?.trim()||null
  return {...row,driver:value||undefined,manualDriver:value}
}

export function setSelectedDriver(row:WeeklyProgrammingRow,driver:{id:string;name:string}|null):WeeklyProgrammingRow{
  const name=driver?.name.trim()||null
  return {...row,driver:name||undefined,driverId:driver?.id||null,manualDriver:name,manualDriverId:driver?.id||null}
}

export function normalizeVehiclePlate(value:string|null|undefined):string|null{return value?.trim().toUpperCase().replace(/[^A-Z0-9]/g,'')||null}
export function setManualComposition(row:WeeklyProgrammingRow,truck:string|null,trailer:string|null):WeeklyProgrammingRow{
  const nextTruck=normalizeVehiclePlate(truck),nextTrailer=normalizeVehiclePlate(trailer)
  const invalid=[...(nextTruck&&!isValidBrazilianPlate(nextTruck)?['cavalo']:[]),...(nextTrailer&&!isValidBrazilianPlate(nextTrailer)?['carreta']:[])]
  if(invalid.length)throw new Error(`Placa inválida: ${invalid.join(' e ')}.`)
  return {...row,truck:nextTruck||undefined,trailer:nextTrailer||undefined,manualTruck:nextTruck,manualTrailer:nextTrailer,supervisionStatus:'PENDING',operationalReleased:false}
}

function preserveManualDriver(current:WeeklyProgrammingRow|undefined,next:WeeklyProgrammingRow):WeeklyProgrammingRow{
  if(!current)return next
  let preserved=Object.prototype.hasOwnProperty.call(current,'manualDriver')?setSelectedDriver({...next,manualDriver:current.manualDriver},current.manualDriverId&&current.manualDriver?{id:current.manualDriverId,name:current.manualDriver}:null):next
  if(Object.prototype.hasOwnProperty.call(current,'manualDriver')&&!Object.prototype.hasOwnProperty.call(current,'manualDriverId'))preserved=setManualDriver({...next,manualDriver:current.manualDriver},current.manualDriver??null)
  if(Object.prototype.hasOwnProperty.call(current,'manualTruck'))preserved={...preserved,truck:current.manualTruck||undefined,manualTruck:current.manualTruck}
  if(Object.prototype.hasOwnProperty.call(current,'manualTrailer'))preserved={...preserved,trailer:current.manualTrailer||undefined,manualTrailer:current.manualTrailer}
  for(const key of ['supervisionStatus','operationalReleased','supervisionUpdatedAt','supervisionUpdatedBy','supervisionReturnReason','supervisionReturnNote','workflowStage','actualStartedAt','actualStartedBy','paymentOrderSentAt','paymentOrderSentBy','paymentConfirmedAt','paymentConfirmedBy','agreedFreightValue','advancePercentage'] as const)if(Object.prototype.hasOwnProperty.call(current,key))preserved={...preserved,[key]:current[key]}
  return preserved
}

export function mergeOnlineUpdates(base:WeeklyProgrammingRow[],online:WeeklyProgrammingRow[]):{rows:WeeklyProgrammingRow[];updatedCount:number;addedCount:number;ignoredNewCount:number;changedStatusLts:string[];changedStatuses:{lt:string;from:WeeklyProgrammingStatus;to:WeeklyProgrammingStatus}[]}{
  const key=(row:WeeklyProgrammingRow)=>`${row.week.trim().toUpperCase()}::${row.lt.trim().toUpperCase()}`
  const onlineByLt=new Map(online.map(row=>[key(row),row]))
  const baseLts=new Set(base.map(row=>key(row)))
  let updatedCount=0
  const changedStatusLts:string[]=[]
  const changedStatuses:{lt:string;from:WeeklyProgrammingStatus;to:WeeklyProgrammingStatus}[]=[]
  const onlineWeeks=new Set(online.map(row=>row.week.trim().toUpperCase()))
  const rows=base.filter(current=>!onlineWeeks.has(current.week.trim().toUpperCase())||onlineByLt.has(key(current))).map(current=>{
    const update=onlineByLt.get(key(current))
    if(!update)return current
    const next=preserveManualDriver(current,{...update,id:current.id,week:current.week,lt:current.lt})
    const comparable=(row:WeeklyProgrammingRow)=>JSON.stringify({...row,id:undefined,sourceRow:undefined})
    if(comparable(next)===comparable(current))return current
    updatedCount++
    if(next.status!==current.status){changedStatusLts.push(current.lt);changedStatuses.push({lt:current.lt,from:current.status,to:next.status})}
    return next
  })
  const added=online.filter(row=>!baseLts.has(key(row)))
  rows.push(...added)
  const addedCount=added.length
  if(addedCount)changedStatusLts.push(...added.map(row=>row.lt))
  return {rows,updatedCount,addedCount,ignoredNewCount:0,changedStatusLts,changedStatuses}
}

function atOffset(now:Date,hours:number):string{const value=new Date(now.getTime()+hours*HOUR_MS);const pad=(part:number)=>String(part).padStart(2,'0');return `${value.getFullYear()}-${pad(value.getMonth()+1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}`}
export function weeklyProgrammingDemo(now=new Date()):WeeklyProgrammingRow[]{
  const base=(data:Omit<WeeklyProgrammingRow,'status'>):WeeklyProgrammingRow=>{const row={...data,status:'OPEN' as WeeklyProgrammingStatus};return {...row,status:classifyWeeklyProgramming(row,now)}}
  return [
    base({id:'demo-01',week:'LHW37',etaOrigin:atOffset(now,-4),origin:'São Bernardo do Campo/SP',destination:'Contagem/MG',vehicleProfile:'Carreta Sider',lt:'LT-CEVA-37001',driver:'Marcos Oliveira',truck:'ABC1D23',trailer:'EFG4H56',pending:[]}),
    base({id:'demo-02',week:'LHW37',etaOrigin:atOffset(now,8),origin:'Betim/MG',destination:'Jaboatão/PE',vehicleProfile:'Carreta Baú',lt:'LT-CEVA-37002',pending:[]}),
    base({id:'demo-04',week:'LHW37',etaOrigin:atOffset(now,52),origin:'Contagem/MG',destination:'São Bernardo do Campo/SP',vehicleProfile:'Carreta Sider',lt:'LT-CEVA-37004',pending:[]}),
    base({id:'demo-05',week:'LHW37',etaOrigin:atOffset(now,71),origin:'Betim/MG',destination:'Extrema/MG',vehicleProfile:'Carreta Baú',lt:'LT-CEVA-37005',driver:'Carlos Lima',truck:'JKL2M34',trailer:'NOP5Q67',pending:[]}),
    {...base({id:'demo-07',week:'LHW37',etaOrigin:atOffset(now,3),origin:'Betim/MG',destination:'Jaboatão/PE',vehicleProfile:'Carreta Sider',lt:'LT-CEVA-37007',pending:[]}),status:'CANCELLED'},
    {...base({id:'demo-08',week:'LHW37',etaOrigin:atOffset(now,2),origin:'Contagem/MG',destination:'Cravinhos/SP',vehicleProfile:'Carreta Baú',lt:'LT-CEVA-37008',driver:'Paulo Rocha',pending:[]}),status:'NOSHOW'},
  ]
}
