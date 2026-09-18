import type { TrafficIncident } from '../types'

export type MapPoint = { latitude:number;longitude:number }

export type IncidentCluster = { latitude:number;longitude:number;incidents:TrafficIncident[] }
export type FocusDriver = {id:string;location?:MapPoint|null;prediction?:{classification?:string|null};route_progress?:{route_state?:string}|null}
export type OperationalHotspot = {latitude:number;longitude:number;score:number;driverCount:number;incidentCount:number;driverIds:string[]}

export function clusterTrafficIncidents(incidents: TrafficIncident[], grid=0.08): IncidentCluster[] {
  const groups=new Map<string,TrafficIncident[]>()
  incidents.forEach((item)=>{const key=`${Math.round(item.latitude/grid)}:${Math.round(item.longitude/grid)}`;groups.set(key,[...(groups.get(key)||[]),item])})
  return [...groups.values()].map((items)=>({latitude:items.reduce((sum,item)=>sum+item.latitude,0)/items.length,longitude:items.reduce((sum,item)=>sum+item.longitude,0)/items.length,incidents:items}))
}

export function filterTrafficIncidents(incidents: TrafficIncident[], traffic: boolean, manual: boolean): TrafficIncident[] {
  return incidents.filter((item)=>(item.manual?manual:traffic)&&item.category!=='RISCO_CLIMATICO')
}

export function completedRoute(geometry: MapPoint[], vehicle?: MapPoint): MapPoint[] {
  const validPoint=(point:MapPoint)=>Number.isFinite(point.latitude)&&Number.isFinite(point.longitude)&&Math.abs(point.latitude)<=90&&Math.abs(point.longitude)<=180
  if (!vehicle || !validPoint(vehicle)) return []
  const validGeometry=geometry.filter(validPoint)
  if (validGeometry.length < 2) return []
  let nearestIndex=0
  let nearestDistance=Number.POSITIVE_INFINITY
  validGeometry.forEach((point,index)=>{
    const latitudeScale=111
    const longitudeScale=111*Math.cos((point.latitude+vehicle.latitude)/2*Math.PI/180)
    const distance=Math.hypot((point.latitude-vehicle.latitude)*latitudeScale,(point.longitude-vehicle.longitude)*longitudeScale)
    if(distance<nearestDistance){nearestDistance=distance;nearestIndex=index}
  })
  const completed=validGeometry.slice(0,nearestIndex+1)
  const nearest=completed[completed.length-1]
  if(nearest.latitude!==vehicle.latitude||nearest.longitude!==vehicle.longitude)completed.push(vehicle)
  return completed
}

export function operationalHotspot(drivers:FocusDriver[],incidents:TrafficIncident[],radiusKm=220):OperationalHotspot|null{
  const vehicles=drivers.filter((driver):driver is FocusDriver&{location:MapPoint}=>validMapPoint(driver.location))
  if(!vehicles.length)return null
  const driverWeight=(driver:FocusDriver)=>driver.prediction?.classification==='CRITICA'?4:driver.prediction?.classification==='ATENCAO'?2:1
  const candidates=vehicles.map((candidate)=>{
    const nearbyDrivers=vehicles.filter((driver)=>distanceKm(candidate.location,driver.location)<=radiusKm)
    const nearbyIncidents=incidents.filter((incident)=>distanceKm(candidate.location,incident)<=radiusKm)
    const score=nearbyDrivers.reduce((sum,driver)=>sum+driverWeight(driver)+(driver.route_progress?.route_state==='OUTSIDE'?3:0),0)+nearbyIncidents.reduce((sum,incident)=>sum+(incident.severity==='CRITICO'?2:1),0)
    return {candidate,nearbyDrivers,nearbyIncidents,score}
  }).sort((left,right)=>right.score-left.score||right.nearbyDrivers.length-left.nearbyDrivers.length)[0]
  const weighted=candidates.nearbyDrivers.map((driver)=>({point:driver.location,weight:driverWeight(driver)+(driver.route_progress?.route_state==='OUTSIDE'?3:0)}))
  const total=weighted.reduce((sum,item)=>sum+item.weight,0)||1
  return {latitude:weighted.reduce((sum,item)=>sum+item.point.latitude*item.weight,0)/total,longitude:weighted.reduce((sum,item)=>sum+item.point.longitude*item.weight,0)/total,score:candidates.score,driverCount:candidates.nearbyDrivers.length,incidentCount:candidates.nearbyIncidents.length,driverIds:candidates.nearbyDrivers.map((driver)=>driver.id)}
}

function validMapPoint(point?:MapPoint|null):point is MapPoint{return Boolean(point&&Number.isFinite(point.latitude)&&Number.isFinite(point.longitude)&&Math.abs(point.latitude)<=90&&Math.abs(point.longitude)<=180)}
function distanceKm(left:MapPoint,right:MapPoint){const radians=Math.PI/180;const latitude=(right.latitude-left.latitude)*radians;const longitude=(right.longitude-left.longitude)*radians;const a=Math.sin(latitude/2)**2+Math.cos(left.latitude*radians)*Math.cos(right.latitude*radians)*Math.sin(longitude/2)**2;return 12742*Math.asin(Math.sqrt(a))}
