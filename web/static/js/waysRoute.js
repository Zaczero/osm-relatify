import { clearAntPath, processRouteAntPath } from './antPathLayer.js'
import { busStopData } from './busStopsLayer.js'
import { processRouteStops, processRouteWarnings, relationId, relationTags } from './menu.js'
import { deflateCompress, deflateDecompress } from './utils.js'
import { startWay, stopWay } from './waysEndpoint.js'
import { waysData } from './waysLayer.js'

export let routeData = null

export function requestCalcBusRoute() {
    if (!startWay || !stopWay || !waysData || !busStopData) {
        clearAntPath()
        return
    }

    const memberWayIdPrefixes = new Set()
    const ways = {}
    const busStops = []

    for (const way of Object.values(waysData)) {
        if (!way.member)
            continue

        ways[way.id] = way

        const prefixIndex = way.id.indexOf('_')
        if (prefixIndex > 0)
            memberWayIdPrefixes.add(way.id.substring(0, prefixIndex))
    }

    for (const way of Object.values(waysData)) {
        if (way.member)
            continue

        const prefixIndex = way.id.indexOf('_')
        if (prefixIndex > 0 && memberWayIdPrefixes.has(way.id.substring(0, prefixIndex)))
            ways[way.id] = way
    }

    for (const busStopCollection of busStopData) {
        if ((busStopCollection.platform && busStopCollection.platform.member) ||
            (busStopCollection.stop && busStopCollection.stop.member))
            busStops.push(busStopCollection)
    }

    calcBusRoute(startWay.id, stopWay.id, ways, busStops, relationTags)
}

const minReconnectInterval = 200
const maxReconnectInterval = 2000
const reconnectIntervalMultiplier = 2
let reconnectInterval = minReconnectInterval

let calcBusRouteScheduledArgs = null
let awaitingResponse = false

const onopen = async () => {
    if (ws.readyState === WebSocket.OPEN)
        reconnectInterval = minReconnectInterval

    if (!calcBusRouteScheduledArgs || awaitingResponse)
        return

    const [startWay, stopWay, ways, busStops, tags] = calcBusRouteScheduledArgs
    calcBusRouteScheduledArgs = null
    awaitingResponse = true

    const body = await deflateCompress({
        relationId: relationId,
        startWay: startWay,
        stopWay: stopWay,
        ways: ways,
        busStops: busStops,
        tags: tags
    })

    ws.send(body)
}

const onmessage = async e => {
    const data = await deflateDecompress(e.data)

    processRouteData(data)
    processRouteAntPath(data)
    processRouteWarnings(data)
    processRouteStops(data)

    awaitingResponse = false
    await onopen()
}

const onclose = async e => {
    console.error(e)
    console.log(`Reconnecting in ${reconnectInterval}ms`)
    awaitingResponse = false

    setTimeout(() => {
        ws = new WebSocket(ws.url)
        ws.binaryType = 'arraybuffer'
        ws.onopen = onopen
        ws.onmessage = onmessage
        ws.onclose = onclose
    }, reconnectInterval)

    reconnectInterval = Math.min(reconnectInterval * reconnectIntervalMultiplier, maxReconnectInterval)
}

let ws = new WebSocket(`${document.location.protocol === 'https:' ? 'wss' : 'ws'}://${document.location.host}/ws/calc_bus_route`)
ws.binaryType = 'arraybuffer'
ws.onopen = onopen
ws.onmessage = onmessage
ws.onclose = onclose

const calcBusRoute = async (...args) => {
    calcBusRouteScheduledArgs = args
    if (ws.readyState === WebSocket.OPEN)
        await onopen()
}

function processRouteData(route) {
    routeData = route
}
