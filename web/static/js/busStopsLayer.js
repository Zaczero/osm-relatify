import { clearBusStopsPopup, showContextMenu } from './busStopsContext.js'
import { map } from './map.js'
import { getBusCollectionName } from './utils.js'
import { waysRBush } from './waysLayer.js'
import { requestCalcBusRoute } from './waysRoute.js'

export let busStopData = null

const inactiveBusStopsLayer = L.layerGroup().addTo(map)
const activeBusStopsLayer = L.layerGroup().addTo(map)

export function processBusStopData(fetchData) {
    if (fetchData) {
        if (fetchData.fetchMerge) {
            const memberSet = new Set()

            if (busStopData) {
                for (const entry of busStopData) {
                    if (entry.platform) {
                        if (entry.platform.member)
                            memberSet.add(`${entry.platform.type},${entry.platform.id}`)
                    }
                    else if (entry.stop) {
                        if (entry.stop.member)
                            memberSet.add(`${entry.stop.type},${entry.stop.id}`)
                    }
                }
            }

            busStopData = fetchData.busStops

            for (const entry of busStopData) {
                if (entry.platform) {
                    const member = memberSet.has(`${entry.platform.type},${entry.platform.id}`)

                    entry.platform.member = member

                    if (entry.stop)
                        entry.stop.member = member
                }
                else if (entry.stop) {
                    const member = memberSet.has(`${entry.stop.type},${entry.stop.id}`)

                    if (entry.platform)
                        entry.platform.member = member

                    entry.stop.member = member
                }
            }
        }
        else {
            busStopData = fetchData.busStops
        }
    }
    else
        busStopData = null

    onBusStopDataChanged()
}

function onBusStopDataChanged() {
    clearBusStopsPopup()
    updateBusStopsVisibility()
    requestCalcBusRoute()
}

export function updateBusStopsVisibility() {
    activeBusStopsLayer.clearLayers()
    inactiveBusStopsLayer.clearLayers()

    if (!busStopData || !waysRBush)
        return

    for (const [i, busStopCollection] of busStopData.entries()) {
        const name = getBusCollectionName(busStopCollection)

        if (busStopCollection.platform)
            addBusStopToLayer(i, busStopCollection.platform, name, 'platform')
        else if (busStopCollection.stop)
            addBusStopToLayer(i, busStopCollection.stop, name, 'stop')
    }
}

const setMemberState = (i, member) => {
    const entry = busStopData[i]

    if (entry.platform)
        entry.platform.member = member

    if (entry.stop)
        entry.stop.member = member

    onBusStopDataChanged()
}

function createBusStopIcon(iconUrl, size) {
    return L.icon({
        className: 'bus-stop-icon',
        iconUrl: iconUrl,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
    })
}

function addBusStopToLayer(i, stop, name, role) {
    if (!stop.member) {
        const nearby = waysRBush.search({
            minX: stop.latLng[0],
            minY: stop.latLng[1],
            maxX: stop.latLng[0],
            maxY: stop.latLng[1],
        })

        if (nearby.length === 0)
            return
    }

    const addToLayer = stop.member ? activeBusStopsLayer : inactiveBusStopsLayer

    const marker = L.marker(stop.latLng, {
        icon: createBusStopIcon(`/static/img/bus_stop_${stop.member ? 'on' : 'off'}.webp`, stop.member ? 24 : 20),
        opacity: stop.member ? 1 : 0.8
    }).addTo(addToLayer)

    marker.bindTooltip(name, {
        direction: 'top',
        offset: [0, -10],
    })

    marker.on('click', () => setMemberState(i, !stop.member))
    marker.on('contextmenu', e => showContextMenu(e, stop))
}
