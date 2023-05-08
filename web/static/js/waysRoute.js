import { clearAntPath, processRouteAntPath } from './antPathLayer.js'
import { busStopData } from './busStopsLayer.js'
import { processRouteStops, processRouteWarnings, relationId } from './menu.js'
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

    calcBusRoute(startWay.id, stopWay.id, ways, busStops)
}

let calcBusRouteAbortController = null

function calcBusRoute(startWay, stopWay, ways, busStops) {
    if (calcBusRouteAbortController)
        calcBusRouteAbortController.abort()

    calcBusRouteAbortController = new AbortController()

    fetch('/calc_bus_route', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            relationId: relationId,
            startWay: startWay,
            stopWay: stopWay,
            ways: ways,
            busStops: busStops
        }),
        signal: calcBusRouteAbortController.signal
    })
        .then(resp => {
            if (!resp.ok) {
                console.error(resp)
                throw new Error('HTTP error')
            }

            return resp.json()
        })
        .then(data => {
            processRouteData(data)
            processRouteAntPath(data)
            processRouteWarnings(data)
            processRouteStops(data)
        })
        .catch(error => {
            if (error.name !== 'AbortError') {
                console.error(error)
                clearAntPath()
                processRouteWarnings({
                    warnings: [{
                        severity: ['HIGH', 999],
                        message: 'Failed to calculate bus route'
                    }]
                })
            }
        })
}

function processRouteData(route) {
    routeData = route
}
