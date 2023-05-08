import { createElementFromHTML } from "./utils.js"

// map
function getInitialMapView() {
    const hash = window.location.hash
    const hashPattern = /map=(\d+)\/(-?\d+\.\d+)\/(-?\d+\.\d+)/

    if (hashPattern.test(hash)) {
        const [_, zoom, lat, lng] = hash.match(hashPattern)
        return [parseFloat(lat), parseFloat(lng), parseInt(zoom, 10)]
    }

    return [52.2320, 21.0068, 6]  // default view
}

const [defaultLat, defaultLng, defaultZoom] = getInitialMapView()

export const map = L.map('map', {
    center: [defaultLat, defaultLng],
    zoom: defaultZoom,
    zoomControl: false,
})

// openstreetmap-like url hash
export function getLocationHash() {
    const center = map.getCenter()
    const zoom = map.getZoom()
    return `map=${zoom}/${center.lat.toFixed(6)}/${center.lng.toFixed(6)}`
}

export const openInOpenStreetMap = path => {
    if (!path)
        path = ''

    window.open(`https://www.openstreetmap.org/${path}#${getLocationHash()}`, '_blank')
}

function updateUrl() {
    window.location.hash = getLocationHash()
}

map.on('moveend', updateUrl)
map.on('zoomend', updateUrl)

// map.on('contextmenu', function (e) {
//     // prevent default right-click context menu from appearing
//     // this is not to hide anything, it's just for convenience
//     e.originalEvent.preventDefault()
// })

// map tiles
const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const baseLayers = {
    'OpenStreetMap': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: attribution,
        maxZoom: 19,
        subdomains: 'abc',
        detectRetina: true,
    }),
    'OpenStreetMap DE': L.tileLayer('https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png', {
        attribution: attribution,
        maxZoom: 19,
        subdomains: 'abcd',
        detectRetina: true,
    }),
    'OpenStreetMap FR': L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
        attribution: attribution,
        maxZoom: 20,
        subdomains: 'abc',
        detectRetina: true,
    }),
}

const selectedBaseLayer = localStorage.getItem('baseLayer')

if (selectedBaseLayer in baseLayers)
    baseLayers[selectedBaseLayer].addTo(map)
else
    baseLayers['OpenStreetMap'].addTo(map)

L.control.layers(baseLayers).addTo(map)

map.on('baselayerchange', e => {
    localStorage.setItem('baseLayer', e.name)
})

// map controls
L.control.zoom({ position: 'topright' }).addTo(map)
L.control.scale().addTo(map)

// open in openstreetmap
class OsmButton extends L.Control {
    constructor(options) {
        super(options)
    }

    onAdd = map => {
        const div = createElementFromHTML(`
            <div class="leaflet-bar leaflet-control leaflet-control-custom" title="Open in OpenStreetMap">
                <a href="javascript:;">
                    <img src="/static/img/openstreetmap.svg" height="24" alt="Open in OpenStreetMap">
                </a>
            </div>`)

        div.onclick = () => openInOpenStreetMap()

        return div
    }
}

new OsmButton({ position: 'topright' }).addTo(map)
