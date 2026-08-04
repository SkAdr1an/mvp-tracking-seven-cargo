import type { TrafficIncident } from '../types'

export type MapPoint = { latitude:number;longitude:number }

export type IncidentCluster = { latitude:number;longitude:number;incidents:TrafficIncident[] }

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
