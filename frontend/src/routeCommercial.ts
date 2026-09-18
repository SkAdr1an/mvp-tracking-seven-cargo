export type TollResponsibility = 'SEVEN' | 'PARTNER' | 'TO_VALIDATE'

export interface CommercialRouteBase {
  aliases: string[]
  label: string
  grossPayment: number | null
  grossReference?: [number, number]
  driverPayment: number | null
  toll: number | null
  partnerFuelReference: number | null
  tollResponsibility: TollResponsibility
}

export interface CommercialValues {
  grossPayment: number | null
  driverPayment: number | null
  toll: number | null
  partnerFuelReference: number | null
  directExtras: number | null
  tollResponsibility: TollResponsibility
}

export const COMMERCIAL_ROUTE_BASES: CommercialRouteBase[] = [
  { aliases:['sao-bernardo-contagem-manual','sao bernardo contagem'], label:'São Bernardo → Contagem', grossPayment:null, grossReference:[6300,6400], driverPayment:5250, toll:148, partnerFuelReference:1560.40, tollResponsibility:'TO_VALIDATE' },
  { aliases:['contagem-guarulhos-cumbica','contagem guarulhos'], label:'Contagem → Guarulhos', grossPayment:4350, driverPayment:3800, toll:148, partnerFuelReference:1369.89, tollResponsibility:'TO_VALIDATE' },
  { aliases:['jaboatao-betim','jaboatao betim'], label:'Jaboatão → Betim', grossPayment:8884, driverPayment:6000, toll:324.05, partnerFuelReference:4800, tollResponsibility:'TO_VALIDATE' },
  { aliases:['jaboatao-palmares','jaboatao palmares'], label:'Jaboatão → Palmares', grossPayment:1225, driverPayment:1100, toll:null, partnerFuelReference:249.77, tollResponsibility:'TO_VALIDATE' },
  { aliases:['betim-jaboatao','betim jaboatao'], label:'Betim → Jaboatão', grossPayment:18107.41, driverPayment:16000, toll:338.65, partnerFuelReference:4970, tollResponsibility:'TO_VALIDATE' },
  { aliases:['curitiba-sao-bento','curitiba sao bento'], label:'Curitiba → São Bento', grossPayment:1360, driverPayment:1100, toll:28.50, partnerFuelReference:253.44, tollResponsibility:'TO_VALIDATE' },
  { aliases:['simoes-filho-recife','simoes filho recife'], label:'Simões Filho → Recife', grossPayment:5300, driverPayment:null, toll:23.10, partnerFuelReference:1866.57, tollResponsibility:'TO_VALIDATE' },
  { aliases:['ibitinga-betim','ibitinga betim'], label:'Ibitinga → Betim', grossPayment:4834.11, driverPayment:null, toll:514.40, partnerFuelReference:1498.37, tollResponsibility:'TO_VALIDATE' },
  { aliases:['itupeva-cariacica','itupeva cariacica'], label:'Itupeva → Cariacica', grossPayment:null, driverPayment:null, toll:500, partnerFuelReference:2288.70, tollResponsibility:'TO_VALIDATE' },
  { aliases:['cariacica-itupeva','cariacica itupeva'], label:'Cariacica → Itupeva', grossPayment:null, driverPayment:null, toll:483, partnerFuelReference:2265.63, tollResponsibility:'TO_VALIDATE' },
]

export function commercialBaseFor(routeId?: string, routeName?: string): CommercialRouteBase | null {
  const candidate = normalize(`${routeId ?? ''} ${routeName ?? ''}`)
  return COMMERCIAL_ROUTE_BASES.find(base => base.aliases.some(alias => candidate.includes(normalize(alias)))) ?? null
}

export function calculateCommercial(values: CommercialValues) {
  const sevenToll = values.tollResponsibility === 'TO_VALIDATE' ? null
    : values.tollResponsibility === 'SEVEN' ? values.toll : 0
  const partnerToll = values.tollResponsibility === 'TO_VALIDATE' ? null
    : values.tollResponsibility === 'PARTNER' ? values.toll : 0
  const resultReady = values.grossPayment != null && values.driverPayment != null
    && sevenToll != null && values.directExtras != null
  const partnerReady = values.driverPayment != null && values.partnerFuelReference != null
    && partnerToll != null
  const grossResult = resultReady
    ? values.grossPayment! - values.driverPayment! - (sevenToll ?? 0) - values.directExtras!
    : null
  return {
    grossResult,
    commercialMargin: grossResult != null && values.grossPayment! > 0
      ? grossResult / values.grossPayment! * 100 : null,
    partnerEconomicReference: partnerReady
      ? values.driverPayment! - values.partnerFuelReference! - (partnerToll ?? 0) : null,
  }
}

function normalize(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}
