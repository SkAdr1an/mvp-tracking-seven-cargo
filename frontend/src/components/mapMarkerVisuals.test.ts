import test from 'node:test'
import assert from 'node:assert/strict'
import {trafficVisual,weatherVisual} from './mapMarkerVisuals.ts'

test('maps traffic categories to distinct operational visuals',()=>{
  assert.deepEqual(trafficVisual({category:'ACIDENTE',severity:'CRITICO',manual:false}),{kind:'accident',severity:'critical',label:'Acidente'})
  assert.equal(trafficVisual({category:'CONGESTIONAMENTO',severity:'ATENCAO',manual:false}).kind,'congestion')
  assert.equal(trafficVisual({category:'VIA_FECHADA',severity:'ATENCAO',manual:false}).kind,'closure')
  assert.equal(trafficVisual({category:'OBRA',severity:'INFORMATIVO',manual:false}).kind,'works')
})

test('distinguishes weather condition and intensity',()=>{
  assert.deepEqual(weatherVisual({type:'rain',severity:'medium',rain_3h_mm:2}),{kind:'light-rain',severity:'attention',label:'Chuva leve'})
  assert.equal(weatherVisual({type:'heavy_rain',severity:'high',rain_3h_mm:14}).kind,'heavy-rain')
  assert.equal(weatherVisual({type:'thunderstorm',severity:'high'}).kind,'storm')
  assert.equal(weatherVisual({type:'low_visibility',severity:'high'}).kind,'fog')
  assert.equal(weatherVisual({type:'strong_wind',severity:'high'}).kind,'wind')
})
