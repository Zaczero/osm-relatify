import { map, openInOpenStreetMap, openInJosm } from './map.js'
import { requestCalcBusRoute } from './waysRoute.js'

let startMarker = null
let stopMarker = null
let popup = null

export let startWay = null
export let stopWay = null

export function processRelationEndpointData(fetchData) {
    if (fetchData) {
        if (fetchData.fetchMerge) {
            if (startWay && !fetchData.ways[startWay.id]) {
                setStartMarker(null)
                clearPopup()
            }

            if (stopWay && !fetchData.ways[stopWay.id]) {
                setStopMarker(null)
                clearPopup()
            }
        }
        else {
            setStartMarker(fetchData.startWay)
            setStopMarker(fetchData.stopWay)
        }
    }
    else {
        setStartMarker(null)
        setStopMarker(null)
        clearPopup()
    }
}

function createEndpointIcon(iconUrl) {
    const size = 24

    return L.icon({
        className: 'endpoint-icon',
        iconUrl: iconUrl,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
    })
}

function onEndpointDataChanged() {
    requestCalcBusRoute()
}

function setStartMarker(way) {
    if (startMarker) {
        startMarker.removeFrom(map)
        startMarker = null
    }

    startWay = way

    if (startWay) {
        startMarker = L.marker(way.midpoint, {
            icon: createEndpointIcon('/static/img/start.webp'),
            interactive: false
        }).addTo(map)
    }

    onEndpointDataChanged()
}

function setStopMarker(way) {
    if (stopMarker) {
        stopMarker.removeFrom(map)
        stopMarker = null
    }

    stopWay = way

    if (stopWay) {
        stopMarker = L.marker(way.midpoint, {
            icon: createEndpointIcon('/static/img/finish.webp'),
            interactive: false
        }).addTo(map)
    }

    onEndpointDataChanged()
}

function clearPopup() {
    if (popup) {
        popup.removeFrom(map)
        popup = null
    }
}

export function showContextMenu(e, way) {
    clearPopup()

    popup = L.popup(e.latlng, {
        content: `
            <div class="btn-group text-center">
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="ep-set-start">
                    <img class="mb-1" src="/static/img/start.webp" width="24" alt="Start icon">
                    <div>Set <b>START</b></div>
                </button>
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="ep-set-stop">
                    <img class="mb-1" src="/static/img/finish.webp" width="24" alt="Finish icon">
                    <div>Set <b>END</b></div>
                </button>
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="ep-open-osm">
                    <img class="mb-1" src="/static/img/openstreetmap.svg" width="24" alt="OpenStreetMap logo">
                    <div>Inspect</div>
                </button>
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="ep-open-josm">
                    <img class="mb-1" src="/static/img/josm.svg" width="24" alt="Josm logo">
                    <div>Inspect</div>
                </button>
            </div>`,
        closeButton: false,
        className: 'popup-sm'
    }).openOn(map)

    const setStartButton = document.getElementById('ep-set-start')
    const setStopButton = document.getElementById('ep-set-stop')
    const openOsmButton = document.getElementById('ep-open-osm')
    const openJosmButton = document.getElementById('ep-open-josm')

    setStartButton.onclick = () => {
        setStartMarker(way)
        popup.close()
    }

    setStopButton.onclick = () => {
        setStopMarker(way)
        popup.close()
    }

    openOsmButton.onclick = () => {
        const id = way.id.split('_')[0]
        openInOpenStreetMap(`way/${id}`)
        popup.close()
    }

    openJosmButton.onclick = () => {
        const id = way.id.split('_')[0]
        openInJosm(`way${id}`)
        popup.close()
    }
}
