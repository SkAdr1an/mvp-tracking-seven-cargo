import assert from 'node:assert/strict'
import test from 'node:test'
import { calculateCommercial, commercialBaseFor } from './routeCommercial.ts'

test('loads every approved commercial route without inventing missing values', () => {
  assert.equal(commercialBaseFor('betim-jaboatao')?.grossPayment, 18107.41)
  assert.deepEqual(commercialBaseFor('sao-bernardo-contagem-manual')?.grossReference, [6300,6400])
  assert.equal(commercialBaseFor('jaboatao-palmares')?.toll, null)
  assert.equal(commercialBaseFor('simoes-filho-recife')?.driverPayment, null)
  assert.equal(commercialBaseFor(undefined, 'Itupeva → Cariacica')?.grossPayment, null)
})

test('Seven result excludes partner fuel and subtracts toll only when Seven assumes it', () => {
  const common = {grossPayment:10000,driverPayment:7000,toll:500,partnerFuelReference:2000,directExtras:250}
  const seven = calculateCommercial({...common,tollResponsibility:'SEVEN'})
  const partner = calculateCommercial({...common,tollResponsibility:'PARTNER'})
  assert.equal(seven.grossResult,2250)
  assert.equal(seven.commercialMargin,22.5)
  assert.equal(partner.grossResult,2750)
  assert.equal(partner.partnerEconomicReference,4500)
})

test('unconfirmed required values remain unavailable', () => {
  const result = calculateCommercial({grossPayment:null,driverPayment:null,toll:null,partnerFuelReference:100,directExtras:0,tollResponsibility:'TO_VALIDATE'})
  assert.equal(result.grossResult,null)
  assert.equal(result.commercialMargin,null)
  assert.equal(result.partnerEconomicReference,null)
})

test('known toll remains out of both results until responsibility is confirmed', () => {
  const result = calculateCommercial({grossPayment:10000,driverPayment:7000,toll:500,partnerFuelReference:2000,directExtras:0,tollResponsibility:'TO_VALIDATE'})
  assert.equal(result.grossResult,null)
  assert.equal(result.commercialMargin,null)
  assert.equal(result.partnerEconomicReference,null)
})
