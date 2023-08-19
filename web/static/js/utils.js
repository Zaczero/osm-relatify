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

export const deflateCompress = async data => {
    if (typeof data !== 'string')
        data = JSON.stringify(data)

    const encoder = new TextEncoder()
    const compressionStream = new CompressionStream('deflate-raw')

    const writer = compressionStream.writable.getWriter()
    writer.write(encoder.encode(data))
    writer.close()

    const reader = compressionStream.readable.getReader()

    let chunks = []
    let totalLength = 0

    while (true) {
        const { done, value } = await reader.read()

        if (done)
            break

        chunks.push(value)
        totalLength += value.length
    }

    let concatenatedChunks = new Uint8Array(totalLength)
    let position = 0

    for (let chunk of chunks) {
        concatenatedChunks.set(chunk, position)
        position += chunk.length
    }

    return concatenatedChunks
}


export const deflateDecompress = async data => {
    const decompressionStream = new DecompressionStream('deflate-raw')

    const writer = decompressionStream.writable.getWriter()
    writer.write(data)
    writer.close()

    const reader = decompressionStream.readable.getReader()

    let chunks = []
    let totalLength = 0

    while (true) {
        const { done, value } = await reader.read()

        if (done)
            break

        chunks.push(value)
        totalLength += value.length
    }

    let concatenatedChunks = new Uint8Array(totalLength)
    let position = 0

    for (let chunk of chunks) {
        concatenatedChunks.set(chunk, position)
        position += chunk.length
    }

    const decoder = new TextDecoder()
    const json = decoder.decode(concatenatedChunks)
    return JSON.parse(json)
}

export const getBusCollectionName = collection => {
    const displayName = stop => {
        if (!stop)
            return ''

        let result = ''

        if (stop.tags.ref)
            result += `<i>${stop.tags.ref}</i> `

        return (result + stop.name).trim()
    }

    const platformName = displayName(collection.platform)
    const stopName = displayName(collection.stop)
    const longestDisplayName = platformName.length >= stopName.length ? platformName : stopName
    return longestDisplayName || '<i>Unnamed</i>'
}
