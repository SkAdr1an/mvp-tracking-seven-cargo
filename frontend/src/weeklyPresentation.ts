import { localDate } from './weeklyProgramming.ts'

const KNOWN_LOCATIONS:Record<string,string>={
  'SOC MG BETIM':'Betim/MG',
  'SOC PE JABOATAO DOS GUARARAPES':'Jaboatão/PE',
  'SOC SP CUMBICA GUARULHOS':'Guarulhos/SP',
  'SOC SP SAO BERNARDO DO CAMPO':'São Bernardo do Campo/SP',
  'SOC MG CONTAGEM INDUSTRIAL':'Contagem/MG',
  'XPT PE PALMARES 02':'Palmares/PE',
}

const normalized=(value:string)=>value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/_/g,' ').replace(/\s+/g,' ').trim().toUpperCase()

export function presentWeeklyLocation(value:string):string{
  const clean=value.trim()
  if(!clean)return clean
  const key=normalized(clean)
  if(KNOWN_LOCATIONS[key])return KNOWN_LOCATIONS[key]
  const match=key.match(/^(?:SOC|XPT) ([A-Z]{2}) (.+)$/)
  if(!match)return clean
  const city=clean.replace(/^(?:SoC|XPT)_[A-Z]{2}_/i,'').replace(/_\d+$/,'').replace(/_/g,' ').replace(/\s+/g,' ').trim()
  return city?`${city}/${match[1]}`:clean
}

export function weeklyDateParts(value:string,referenceTime:Date):{dayLabel:string;timeLabel:string}{
  const date=localDate(value)
  const start=(input:Date)=>new Date(input.getFullYear(),input.getMonth(),input.getDate()).getTime()
  const dayDifference=Math.round((start(date)-start(referenceTime))/86_400_000)
  const dayLabel=dayDifference===0?'HOJE':dayDifference===1?'AMANHÃ':date.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'})
  return {dayLabel,timeLabel:date.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
}
