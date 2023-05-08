import { updateBusStopsVisibility } from './busStopsLayer.js'
import { map } from './map.js'
import { showContextMenu, startWay, stopWay } from './waysEndpoint.js'
import { requestCalcBusRoute } from './waysRoute.js'

export let waysData = null
export let waysRBush = null

const waysLayer = L.layerGroup().addTo(map)

export function processRelationWaysData(fetchData) {
    if (fetchData)
        waysData = fetchData.ways
    else
        waysData = null

    onWaysDataChanged()

    if (waysData)
        fitToBounds(fetchData.bounds)
}

function createWaysRBush() {
    if (!waysData)
        return null

    const maxDistanceMeters = 250
    const maxDistance = maxDistanceMeters / 111111
    const segmentBoundingBoxes = []

    for (const way of Object.values(waysData)) {
        if (!way.member)
            continue

        for (let i = 0; i < way.latLngs.length - 1; i++) {
            const start = way.latLngs[i]
            const end = way.latLngs[i + 1]

            const bbox = {
                minX: Math.min(start[0], end[0]) - maxDistance,
                minY: Math.min(start[1], end[1]) - maxDistance,
                maxX: Math.max(start[0], end[0]) + maxDistance,
                maxY: Math.max(start[1], end[1]) + maxDistance,
            }

            segmentBoundingBoxes.push(bbox)
        }
    }

    const tree = rbush()
    tree.load(segmentBoundingBoxes)
    return tree
}

function onWaysDataChanged() {
    waysRBush = createWaysRBush()

    updateWaysVisibility()
    updateBusStopsVisibility()

    requestCalcBusRoute()
}

function updateWaysVisibility() {
    if (!waysData) {
        waysLayer.clearLayers()
        return
    }

    const visibleWays = new Set()

    for (const way of Object.values(waysData)) {
        if (!way.member)
            continue

        // add the way itself ..
        visibleWays.add(way.id)

        // .. and all the ways it is connected to
        for (const connectedWayId of way.connectedTo) {
            visibleWays.add(connectedWayId)
        }
    }

    // store each line in a separate array,
    // so that we can add them in the right order
    const lines = {
        memberLines: [],
        memberBuffers: [],
        memberBuffers2: [],
        nonMemberLines: [],
        nonMemberBuffers: [],
        nonMemberBuffers2: [],
    }

    for (const wayId of visibleWays) {
        const way = waysData[wayId]
        const [lineEx, buffer, buffer2] = addWayToLayer(way)

        if (way.member) {
            lines.memberLines.push(...lineEx)
            lines.memberBuffers.push(buffer)
            lines.memberBuffers2.push(buffer2)
        }
        else {
            lines.nonMemberLines.push(...lineEx)
            lines.nonMemberBuffers.push(buffer)
            lines.nonMemberBuffers2.push(buffer2)
        }
    }

    waysLayer.clearLayers()

    for (const line of [
        ...lines.nonMemberBuffers,
        ...lines.memberBuffers,
        ...lines.nonMemberBuffers2,
        ...lines.memberBuffers2,
        ...lines.nonMemberLines,
        ...lines.memberLines]) {
        line.addTo(waysLayer)
    }
}

function addWayToLayer(way) {
    const lineColor = way.member ? 'orangered' : '#909090'
    const lineHoverColor = way.member ? 'darkred' : '#4C4C4C'
    const lineWeight = way.member ? 7 : 5

    const line = L.polyline(way.latLngs, {
        color: lineColor,
        weight: lineWeight,
    })

    const buffer = L.polyline(way.latLngs, {
        color: 'transparent',
        weight: lineWeight + 18,
    })

    const buffer2 = L.polyline(way.latLngs, {
        color: 'transparent',
        weight: lineWeight + 9,
    })

    const decorators = []

    if (way.oneway) {
        line.arrowheads({
            size: Math.min(15, way.length * .6) + 'm',
            frequency: way.length > 40 ? '40m' : 'endonly',
            yawn: 40,
            stroke: false,
            fill: true,
            fillColor: lineHoverColor,
        })
    }

    const onClickHandler = () => {
        if (way.id === startWay.id || way.id === stopWay.id)
            return

        waysData[way.id].member = !way.member
        onWaysDataChanged()
    }

    const onMouseOverHandler = () => {
        line.setStyle({
            color: lineHoverColor,
            weight: lineWeight + 2
        })
    }

    const onMouseOutHandler = () => {
        line.setStyle({
            color: lineColor,
            weight: lineWeight
        })
    }

    const onContextMenuHandler = (e) => {
        showContextMenu(e, way)
    }

    for (const e of [line, ...decorators, buffer, buffer2]) {
        e.on('click', onClickHandler)
        e.on('mouseover', onMouseOverHandler)
        e.on('mouseout', onMouseOutHandler)

        if (way.member) {
            e.on('contextmenu', onContextMenuHandler)
        }
    }

    return [[line, ...decorators], buffer, buffer2]
}

function fitToBounds(bounds) {
    const southWest = L.latLng(bounds.minlat, bounds.minlon)
    const northEast = L.latLng(bounds.maxlat, bounds.maxlon)
    const latLngBounds = L.latLngBounds(southWest, northEast)
    map.fitBounds(latLngBounds)
}
