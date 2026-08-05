import test from 'node:test'
import assert from 'node:assert/strict'
import { clusterStations } from './stationMapUtils.ts'
import type { HomologatedStation } from '../types.ts'

const station=(id:string,latitude:number,longitude:number,status='validated'):HomologatedStation=>({
  post_id:id,canonical_name:id,city:'Betim',uf:'MG',latitude,longitude,
  map_validation_status:status as HomologatedStation['map_validation_status'],
  source_name:'AngelLira',source_version:'v1',
})

test('clusters nearby validated stations at distant zoom',()=>{
  const result=clusterStations([station('a',-20,-44),station('b',-20.01,-44.01),station('c',-8,-35)],6)
  assert.equal(result.length,2)
  assert.deepEqual(result.map((item)=>item.stations.length).sort(),[1,2])
})

test('keeps individual markers at close zoom and excludes unsafe records',()=>{
  const values=[station('a',-20,-44),station('b',-20.001,-44.001),station('unsafe',-20,-44,'pending_review')]
  assert.deepEqual(clusterStations(values,13).map((item)=>item.id),['a','b'])
})
