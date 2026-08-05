import { divIcon, latLngBounds } from 'leaflet'
import { Marker, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { useMemo, useState } from 'react'
import type { AngelLiraStationsResponse } from '../types'
import { clusterStations } from './stationMapUtils'

export function HomologatedStationsLayer({ data }: { data: AngelLiraStationsResponse }) {
  const map = useMap()
  const [zoom,setZoom]=useState(map.getZoom())
  useMapEvents({zoomend(event){setZoom(event.target.getZoom())}})
  const clusters=useMemo(()=>clusterStations(data.stations,zoom),[data.stations,zoom])
  return <>{clusters.map((cluster)=>{
    if(cluster.stations.length>1) return <Marker key={cluster.id} position={[cluster.latitude,cluster.longitude]} icon={stationIcon(String(cluster.stations.length),true)} eventHandlers={{click:()=>{
      const bounds=latLngBounds(cluster.stations.map((station)=>[station.latitude,station.longitude] as [number,number]))
      map.fitBounds(bounds.pad(.35),{maxZoom:13})
    }}}><Tooltip>{cluster.stations.length} postos homologados</Tooltip></Marker>
    const station=cluster.stations[0]
    return <Marker key={station.post_id} position={[station.latitude,station.longitude]} icon={stationIcon('P',false)}>
      <Tooltip>{station.canonical_name}</Tooltip>
      <Popup><div className="station-popup"><strong>{station.canonical_name}</strong><span>{station.city}/{station.uf}</span>{station.road&&<span>{station.road}{station.km!=null&&station.km!==''?` · km ${station.km}`:''}</span>}{station.phone&&<span>Telefone: {station.phone}</span>}<small>Fonte: {station.source_name||data.source} · versão {station.source_version||data.dataset?.source_version||'não informada'}</small><small>Status: validado</small><em>Referência visual — não gera alerta.</em></div></Popup>
    </Marker>
  })}</>
}

function stationIcon(label:string,cluster:boolean){return divIcon({className:'map-div-icon',html:`<span class="map-symbol map-symbol--station${cluster?' map-symbol--station-cluster':''}">${label}</span>`,iconSize:[34,34],iconAnchor:[17,17]})}
