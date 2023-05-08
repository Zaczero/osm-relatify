export const haversine_distance = (latLng1, latLng2) => {
    const R = 6371000 // metres

    const toRadians = (degrees) => degrees * Math.PI / 180

    const φ1 = toRadians(latLng1[0]) // φ, λ in radians
    const φ2 = toRadians(latLng2[0])
    const Δφ = toRadians(latLng2[0] - latLng1[0])
    const Δλ = toRadians(latLng2[1] - latLng1[1])

    const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))

    return R * c // in metres
}

export const createElementFromHTML = html => {
    let body = undefined

    html = html.trim()

    if (html.startsWith('<tr'))
        body = document.createElement('tbody')
    else
        body = document.createElement('div')

    body.innerHTML = html
    return body.firstChild
}
