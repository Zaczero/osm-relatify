import { map } from "./map.js"

let antPath = null

export function clearAntPath() {
    if (antPath) {
        antPath.removeFrom(map)
        antPath = null
    }
}

export function processRouteAntPath(route) {
    clearAntPath()

    antPath = L.polyline
        .antPath(route.latLngs, {
            delay: 3500,
            weight: 4,
            dashArray: [22, 20],
            color: "transparent",
            pulseColor: "#ffffff",
            opacity: 0.75,
            interactive: false,
        })
        .addTo(map)
}
