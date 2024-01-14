import { map, openInOpenStreetMap, openInJosm } from './map.js'

let popup = null

export function clearBusStopsPopup() {
    if (popup) {
        popup.removeFrom(map)
        popup = null
    }
}

export function showContextMenu(e, stop) {
    clearBusStopsPopup()

    popup = L.popup(e.latlng, {
        content: `
            <div class="btn-group text-center">
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="bs-open-osm">
                    <img class="mb-1" src="/static/img/openstreetmap.svg" width="24" alt="OpenStreetMap logo">
                    <div>Inspect</div>
                </button>
                <button class="btn btn-sm btn-light d-flex flex-column align-items-center" id="bs-open-josm">
                    <img class="mb-1" src="/static/img/josm.svg" width="24" alt="Josm logo">
                    <div>Inspect</div>
                </button>
            </div>`,
        closeButton: false,
        className: 'popup-sm'
    }).openOn(map)

    const openOsmButton = document.getElementById('bs-open-osm')
    const openJosmButton = document.getElementById('bs-open-josm')

    openOsmButton.onclick = () => {
        const id = stop.id.split('_')[0]
        openInOpenStreetMap(`${stop.type}/${id}`)
        popup.close()
    }

    openJosmButton.onclick = () => {
        const id = stop.id.split('_')[0]
        openInJosm(`${stop.type}${id}`)
        popup.close()
    }
}
