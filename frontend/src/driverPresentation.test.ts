import assert from 'node:assert/strict'
import test from 'node:test'
import { operationalAvailability, progressLabel } from './driverPresentation.ts'

test('driver progress tolerates absent and incomplete provider data', () => {
  assert.equal(progressLabel({}), 'Indisponível')
  assert.equal(progressLabel({ route_progress: {} as never }), 'Indisponível')
  assert.equal(progressLabel({ route_progress: { progress_percent: Number.NaN } as never }), 'Indisponível')
})

test('driver progress formats valid provider data', () => {
  assert.match(progressLabel({ route_progress: { progress_percent: 42.5 } as never }), /^42[,.]5%$/)
})

test('sanitized Anderson payload reports missing geometry instead of throwing',()=>{
  const issue=operationalAvailability({id:'PPV6F40',status:'on_route',location:{latitude:-23.7198,longitude:-46.6022},route_recognition:{status:'RECOGNIZED',method:'provider_endpoints',reason:'sao_bernardo_to_contagem'},operational:{route:{id:'sao-bernardo-contagem-manual'} as never} as never,route_progress:{confidence:'UNAVAILABLE',reason:'geometry_unavailable',position_at:'2026-08-03T14:31:07+00:00',speed_kmh:null,speed_state:'UNAVAILABLE'} as never})
  assert.deepEqual(issue,{code:'ROUTE_GEOMETRY_UNAVAILABLE',message:'Geometria da rota indisponível'})
})

test('operational availability distinguishes known incomplete states',()=>{
  const base={id:'ABC1D23',status:'on_route' as const}
  assert.equal(operationalAvailability({...base,route_recognition:{status:'UNIDENTIFIED',method:'test',reason:'test'}})?.code,'ROUTE_NOT_RECOGNIZED')
  assert.equal(operationalAvailability({...base,location:{latitude:0,longitude:0},route_recognition:{status:'RECOGNIZED',method:'test',reason:'test'}})?.code,'ROUTE_CONFIG_UNAVAILABLE')
  assert.equal(operationalAvailability({...base,operational:{route:{id:'route'} as never} as never,route_recognition:{status:'RECOGNIZED',method:'test',reason:'test'}})?.code,'POSITION_UNAVAILABLE')
  assert.equal(operationalAvailability({...base,location:{latitude:0,longitude:0},operational:{route:{id:'route'} as never,driver_divergence:true} as never,route_recognition:{status:'RECOGNIZED',method:'test',reason:'test'}})?.code,'DRIVER_LINK_INCONSISTENT')
  assert.equal(operationalAvailability({...base,location:{latitude:0,longitude:0},operational:{route:{id:'route'} as never} as never,route_recognition:{status:'RECOGNIZED',method:'test',reason:'test'},route_progress:{confidence:'HIGH'} as never})?.code,'OPERATIONAL_DATA_INCOMPLETE')
})
