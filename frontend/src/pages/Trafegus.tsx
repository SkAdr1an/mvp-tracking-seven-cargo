import { CalendarClock, CarFront, MapPinned, Search, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { FormEvent, ReactNode, useState } from 'react'
import { api } from '../api'
import type { ProviderResult } from '../types'
import { HistoryContent } from './DriverHistory'

type DataRecord = Record<string, unknown>

const labels: Record<string, string> = {
  placa: 'Placa', frota: 'Frota', marca: 'Marca', modelo: 'Modelo',
  ano_fabricacao: 'Ano de fabricação', ano_modelo: 'Ano do modelo',
  renavam: 'Renavam', chassi: 'Chassi', cor: 'Cor',
  nome_transportador: 'Transportadora', nome_embarcador: 'Embarcador',
  descricao_ope: 'Operação', viagem_usuario_adicionou: 'Criada por',
  data_primeira_posicao_viagem: 'Início da viagem', data_ultima_posicao_viagem: 'Última atualização',
  latitude: 'Latitude', longitude: 'Longitude', velocidade: 'Velocidade',
  data_posicao: 'Data da posição', ignicao: 'Ignição', cidade: 'Cidade', uf: 'UF',
  descricao: 'Descrição', tipo: 'Tipo', data_evento: 'Data do evento',
}

export function Trafegus() {
  const [mode, setMode] = useState<'drivers'|'plate'>('drivers')
  return <div className="page-stack">
    <nav className="trafegus-tabs" aria-label="Tipo de consulta">
      <button className={mode==='drivers'?'active':''} onClick={()=>setMode('drivers')}>Histórico por motorista</button>
      <button className={mode==='plate'?'active':''} onClick={()=>setMode('plate')}>Consulta por placa</button>
    </nav>
    {mode==='drivers'?<HistoryContent/>:<PlateConsultation/>}
  </div>
}

function PlateConsultation() {
  const [plate, setPlate] = useState('')
  const consultation = useMutation({ mutationFn: api.consultPlate })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    consultation.mutate(plate.replace(/[^a-zA-Z0-9]/g, '').toUpperCase())
  }
  const result = consultation.data

  return <div className="page-stack">
    <section className="panel plate-search"><div><span className="eyebrow">Trafegus</span><h2>Localize um veículo pela placa</h2><p>A consulta recupera os dados mais recentes disponíveis no provedor.</p></div><form onSubmit={submit}><label><Search size={19} /><input value={plate} maxLength={8} onChange={(e) => setPlate(e.target.value.toUpperCase())} placeholder="ABC1D23" aria-label="Placa do veículo" /></label><button className="primary-button" disabled={consultation.isPending || plate.length < 7}>{consultation.isPending ? 'Consultando...' : 'Consultar placa'}</button></form></section>
    {consultation.error && <div className="error-banner"><TriangleAlert size={20} /><div><strong>Não foi possível consultar o Trafegus</strong><span>{consultation.error.message}</span></div></div>}
    {!result ? <section className="panel provider-empty"><div><ShieldCheck size={34} /></div><h2>Consulta segura e somente leitura</h2><p>Documentos são mascarados e nenhuma credencial ou token é enviado ao navegador.</p></section> : <><div className="result-title"><div><span className="eyebrow">Resultado</span><h2>Veículo {result.plate}</h2></div><em className="badge badge--on_route">Consulta concluída</em></div><section className="provider-grid"><VehicleCard result={result.vehicle} /><PositionCard result={result.last_position} /><EventsCard result={result.events} /><TripCard result={result.trip} /></section></>}
  </div>
}

function VehicleCard({ result }: { result: ProviderResult }) {
  const vehicle = firstRecord(result.data?.veiculo)
  return <ProviderCard icon={<CarFront size={20} />} title="Veículo" result={result} empty={!vehicle} emptyText="Veículo não encontrado"><DataGrid record={vehicle} fields={['placa', 'frota', 'marca', 'modelo', 'ano_fabricacao', 'ano_modelo', 'renavam', 'chassi', 'cor']} /></ProviderCard>
}

function PositionCard({ result }: { result: ProviderResult }) {
  const position = firstRecord(result.data?.Posicao ?? result.data?.posicao)
  return <ProviderCard icon={<MapPinned size={20} />} title="Última posição" result={result} empty={!position} emptyText="Nenhuma posição disponível para este veículo"><DataGrid record={position} fields={['data_posicao', 'cidade', 'uf', 'latitude', 'longitude', 'velocidade', 'ignicao']} />{position && coordinates(position) && <a className="map-link" href={`https://www.openstreetmap.org/?mlat=${coordinates(position)![0]}&mlon=${coordinates(position)![1]}#map=14/${coordinates(position)![0]}/${coordinates(position)![1]}`} target="_blank" rel="noreferrer">Abrir posição no mapa</a>}</ProviderCard>
}

function EventsCard({ result }: { result: ProviderResult }) {
  const events = records(result.data?.eventos)
  return <ProviderCard icon={<TriangleAlert size={20} />} title="Eventos" result={result} empty={!events.length} emptyText="Nenhum evento encontrado"><div className="record-list">{events.slice(0, 5).map((event, index) => <div className="record-item" key={index}><DataGrid record={event} fields={['descricao', 'tipo', 'data_evento', 'cidade', 'uf']} /></div>)}</div></ProviderCard>
}

function TripCard({ result }: { result: ProviderResult }) {
  const trip = firstRecord(result.data?.viagens ?? result.data?.viagem)
  return <ProviderCard icon={<CalendarClock size={20} />} title="Última viagem" result={result} empty={!trip} emptyText="Nenhuma viagem encontrada"><DataGrid record={trip} fields={['nome_transportador', 'nome_embarcador', 'descricao_ope', 'viagem_usuario_adicionou', 'data_primeira_posicao_viagem', 'data_ultima_posicao_viagem']} /></ProviderCard>
}

function ProviderCard({ icon, title, result, empty, emptyText, children }: { icon: ReactNode; title: string; result: ProviderResult; empty: boolean; emptyText: string; children: ReactNode }) {
  const available = result.ok && !empty
  return <article className="panel provider-card"><div className="provider-card__title"><i>{icon}</i><h3>{title}</h3><span className={available ? 'service-up' : result.ok ? 'service-empty' : 'service-down'}>{available ? 'Dados encontrados' : result.ok ? 'Sem dados' : `HTTP ${result.http_status}`}</span></div>{!result.ok ? <EmptyState icon={<TriangleAlert />} text={result.error || 'Consulta indisponível'} error /> : empty ? <EmptyState icon={icon} text={emptyText} /> : children}</article>
}

function EmptyState({ icon, text, error = false }: { icon: ReactNode; text: string; error?: boolean }) {
  return <div className={`provider-state ${error ? 'provider-state--error' : ''}`}><span>{icon}</span><strong>{text}</strong><small>{error ? 'Tente novamente em alguns instantes.' : 'O provedor respondeu normalmente, mas não enviou registros.'}</small></div>
}

function DataGrid({ record, fields }: { record: DataRecord | null; fields: string[] }) {
  if (!record) return null
  const visible = fields.filter((field) => record[field] !== null && record[field] !== undefined && record[field] !== '')
  return <dl className="provider-data">{visible.map((field) => <div key={field}><dt>{labels[field] || field.replaceAll('_', ' ')}</dt><dd>{formatValue(record[field], field)}</dd></div>)}</dl>
}

function records(value: unknown): DataRecord[] {
  if (Array.isArray(value)) return value.filter((item): item is DataRecord => !!item && typeof item === 'object' && !Array.isArray(item))
  if (value && typeof value === 'object') return [value as DataRecord]
  return []
}
function firstRecord(value: unknown): DataRecord | null { return records(value)[0] || null }
function formatValue(value: unknown, field: string): string {
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não'
  if (field.includes('data_') && typeof value === 'string') { const date = new Date(value); if (!Number.isNaN(date.getTime())) return date.toLocaleString('pt-BR') }
  return String(value)
}
function coordinates(record: DataRecord): [number, number] | null {
  const lat = Number(record.latitude ?? record.lat)
  const lon = Number(record.longitude ?? record.lon ?? record.lng)
  return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null
}
