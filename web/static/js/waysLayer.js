import { updateBusStopsVisibility } from "./busStopsLayer.js"
import { downloadTrigger } from "./downloadTriggers.js"
import { canvasRenderer, map } from "./map.js"
import { showContextMenu, startWay, stopWay } from "./waysEndpoint.js"
import { requestCalcBusRoute } from "./waysRoute.js"

export let waysData = null
export let waysRBush = null

map.createPane("nonMemberBuffers").style.zIndex = 394
map.createPane("memberBuffers").style.zIndex = 395
map.createPane("nonMemberBuffers2").style.zIndex = 396
map.createPane("memberBuffers2").style.zIndex = 397
map.createPane("nonMemberWays").style.zIndex = 398
map.createPane("memberWays").style.zIndex = 399

const waysLayer = L.layerGroup().addTo(map)

let idGroupMap = new Map()

export function processRelationWaysData(fetchData) {
    if (fetchData) {
        if (fetchData.fetchMerge) {
            const memberMap = new Map()

            if (waysData) {
                for (const way of Object.values(waysData)) {
                    memberMap.set(way.id, way.member)
                    memberMap.set(way.id.split("_")[0], way.member)
                }
            }

            waysData = fetchData.ways

            for (const way of Object.values(waysData)) {
                const memberCandidates = [memberMap.get(way.id), memberMap.get(way.id.split("_")[0])]

                way.member = memberCandidates.find((m) => m !== undefined) || false
            }
        } else {
            waysData = fetchData.ways
        }
    } else waysData = null

    onWaysDataChanged()

    if (waysData && !fetchData?.fetchMerge) {
        fitToBounds(fetchData.bounds)
    }
}

function createWaysRBush() {
    if (!waysData) return null

    const maxDistanceMeters = 250
    const maxDistance = maxDistanceMeters / 111111
    const segmentBoundingBoxes = []

    for (const way of Object.values(waysData)) {
        if (!way.member) continue

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
        idGroupMap = new Map()
        waysLayer.clearLayers()
        return
    }

    const visibleWays = new Set()

    for (const way of Object.values(waysData)) {
        if (!way.member) continue

        // add the way itself ..
        visibleWays.add(way.id)

        // .. and all the ways it is connected to
        for (const connectedWayId of way.connectedTo) {
            visibleWays.add(connectedWayId)
        }
    }

    for (const wayId of visibleWays) {
        addWay(waysData[wayId])
    }

    for (const wayId of idGroupMap.keys()) {
        if (!visibleWays.has(wayId)) {
            removeGroupFromLayers(wayId)
        }
    }
}

const addWay = (way) => {
    if (idGroupMap.has(way.id)) return

    const lineColor = way.member ? "orangered" : "#444"
    const lineHoverColor = way.member ? "darkred" : "#000"
    const lineWeight = way.member ? 7 : 5
    const opacity = way.member ? 1 : 0.55

    const line = L.polyline(way.latLngs, {
        renderer: canvasRenderer,
        color: lineColor,
        opacity: opacity,
        weight: lineWeight,
        pane: way.member ? "memberWays" : "nonMemberWays",
    })

    const buffer = L.polyline(way.latLngs, {
        renderer: canvasRenderer,
        color: "transparent",
        weight: lineWeight + 18,
        pane: way.member ? "memberBuffers" : "nonMemberBuffers",
    })

    const buffer2 = L.polyline(way.latLngs, {
        renderer: canvasRenderer,
        color: "transparent",
        weight: lineWeight + 9,
        pane: way.member ? "memberBuffers2" : "nonMemberBuffers2",
    })

    if (way.oneway) {
        line.arrowheads({
            size: `${Math.min(15, way.length * 0.6)}m`,
            frequency: way.length > 40 ? "40m" : "endonly",
            yawn: 40,
            stroke: false,
            fill: true,
            fillColor: lineHoverColor,
            fillOpacity: opacity,
        })
    }

    const group = [line, buffer, buffer2]

    const onClickHandler = () => {
        if (way.id === startWay.id || way.id === stopWay.id) return

        const newMember = !way.member

        waysData[way.id].member = newMember
        removeGroupFromLayers(way.id)
        onWaysDataChanged()

        if (newMember) downloadTrigger(way.id)
    }

    const onMouseOverHandler = () => {
        line.setStyle({
            color: lineHoverColor,
            weight: lineWeight + 2,
        })
    }

    const onMouseOutHandler = () => {
        line.setStyle({
            color: lineColor,
            weight: lineWeight,
        })
    }

    const onContextMenuHandler = (e) => {
        showContextMenu(e, way)
    }

    for (const e of group) {
        e.on("click", onClickHandler)
        e.on("mouseover", onMouseOverHandler)
        e.on("mouseout", onMouseOutHandler)

        if (way.member) e.on("contextmenu", onContextMenuHandler)
    }

    addGroupToLayers(way.id, group)
}

export const removeMembersList = (wayIds) => {
    for (const wayId of wayIds) {
        if (wayId === startWay.id || wayId === stopWay.id) continue

        waysData[wayId].member = false
        removeGroupFromLayers(wayId)
    }

    onWaysDataChanged()
}

const addGroupToLayers = (id, group) => {
    if (idGroupMap.has(id)) return

    const [line, buffer, buffer2] = group

    waysLayer.addLayer(buffer)
    waysLayer.addLayer(buffer2)
    waysLayer.addLayer(line)

    idGroupMap.set(id, group)
}

const removeGroupFromLayers = (id) => {
    if (!idGroupMap.has(id)) return

    const [line, buffer, buffer2] = idGroupMap.get(id)

    waysLayer.removeLayer(buffer)
    waysLayer.removeLayer(buffer2)
    waysLayer.removeLayer(line)

    idGroupMap.delete(id)
}

function fitToBounds(bounds) {
    const southWest = L.latLng(bounds.minlat, bounds.minlon)
    const northEast = L.latLng(bounds.maxlat, bounds.maxlon)
    const latLngBounds = L.latLngBounds(southWest, northEast)
    map.fitBounds(latLngBounds)
}
