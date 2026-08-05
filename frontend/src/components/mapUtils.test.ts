import test from 'node:test'
import assert from 'node:assert/strict'
import { clusterTrafficIncidents, completedRoute, filterTrafficIncidents } from './mapUtils.ts'
import type { TrafficIncident } from '../types.ts'

const incident=(id:string,latitude:number,longitude:number,manual=false,category='ACIDENTE'):TrafficIncident=>({id,route_id:'route',category:category as TrafficIncident['category'],severity:'ATENCAO',source:'test',description:'test',latitude,longitude,geometry:{type:'Point',coordinates:[longitude,latitude]},delay_already_in_eta:true,updated_at:new Date().toISOString(),expires_at:new Date(Date.now()+60000).toISOString(),status:'ACTIVE',manual,affected_vehicles:[]})

test('groups nearby markers without duplicating incidents',()=>{const result=clusterTrafficIncidents([incident('1',-20,-44),incident('2',-20.01,-44.01),incident('3',-19,-43)]);assert.equal(result.length,2);assert.deepEqual(result.map((group)=>group.incidents.length).sort(),[1,2])})
test('filters traffic and manual layers independently and hides climate duplication',()=>{const values=[incident('traffic',-20,-44),incident('manual',-20,-44,true),incident('weather',-20,-44,false,'RISCO_CLIMATICO')];assert.deepEqual(filterTrafficIncidents(values,true,false).map((item)=>item.id),['traffic']);assert.deepEqual(filterTrafficIncidents(values,false,true).map((item)=>item.id),['manual'])})
test('fills from origin only up to the vehicle',()=>{const geometry=[{latitude:0,longitude:0},{latitude:0,longitude:1},{latitude:0,longitude:2},{latitude:0,longitude:3}];const result=completedRoute(geometry,{latitude:.01,longitude:1.1});assert.deepEqual(result.slice(0,2),geometry.slice(0,2));assert.deepEqual(result.at(-1),{latitude:.01,longitude:1.1});assert.equal(result.some((point)=>point.longitude===2),false)})
test('missing or invalid geometry and vehicle positions cannot break progress rendering',()=>{const valid=[{latitude:0,longitude:0},{latitude:0,longitude:1}];assert.deepEqual(completedRoute([],valid[0]),[]);assert.deepEqual(completedRoute(valid),[]);assert.deepEqual(completedRoute(valid,{latitude:Number.NaN,longitude:0}),[]);assert.deepEqual(completedRoute([{latitude:999,longitude:0},...valid],{latitude:0,longitude:.5}).slice(0,1),valid.slice(0,1))})

test('map restores progress from the matching official route without inventing data',async()=>{
  const source=await import('node:fs').then(({readFileSync})=>readFileSync(new URL('./DriverMap.tsx',import.meta.url),'utf8'))
  assert.match(source,/item\.trip_key===driver\.operational\?\.trip_key/)
  assert.match(source,/driver\.operational\?\.route_id\|\|path\?\.route_id/)
  assert.match(source,/completedRoute\(route\?\.geometry\|\|\[\],driver\.location\)/)
  assert.match(source,/key=\{`progress-\$\{tripKey\}`\}/)
  assert.doesNotMatch(source,/traffic\?\.routes\[0\]/)
})

test('map viewport fits eligible drivers and resize only repairs dimensions',async()=>{
  const {readFileSync}=await import('node:fs')
  const map=readFileSync(new URL('./DriverMap.tsx',import.meta.url),'utf8')
  const controller=readFileSync(new URL('./MapResizeController.tsx',import.meta.url),'utf8')
  assert.match(map,/filters\.trucks\?drivers\.flatMap/)
  assert.match(map,/command=\{cameraCommand\}/)
  assert.match(controller,/map\.invalidateSize/)
  assert.match(controller,/map\.fitBounds/)
  assert.match(controller,/command\.mode === 'focus'/)
  assert.match(controller,/map\.setView\(command\.point, 12/)
  assert.match(controller,/initialFitDone\.current/)
  assert.match(controller,/paddingTopLeft/)
  assert.match(controller,/paddingBottomRight/)
  assert.match(controller,/ResizeObserver/)
  assert.match(controller,/MutationObserver/)
  const resizeEffect=controller.slice(controller.indexOf("const container = map.getContainer()"))
  assert.doesNotMatch(resizeEffect,/fitBounds|setView/)
})

test('polling data changes update stable progress layers without issuing camera commands',async()=>{
  const source=await import('node:fs').then(({readFileSync})=>readFileSync(new URL('./DriverMap.tsx',import.meta.url),'utf8'))
  const overview=await import('node:fs').then(({readFileSync})=>readFileSync(new URL('../pages/Overview.tsx',import.meta.url),'utf8'))
  assert.match(source,/progressLines\.map/)
  assert.match(source,/key=\{`progress-\$\{tripKey\}`\}/)
  assert.match(overview,/changeFilter=.*fitVisible\(\)/)
  assert.match(overview,/selected\?\.id===driver\.id.*onClear\(\);fitVisible\(\)/)
  assert.match(overview,/mode:'focus'/)
  assert.doesNotMatch(source,/fitKey/)
})
