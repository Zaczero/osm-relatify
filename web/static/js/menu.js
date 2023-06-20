import { processBusStopData } from './busStopsLayer.js'
import { processRelationDownloadTriggers } from './downloadTriggers.js'
import { showMessage } from './messageBox.js'
import { createElementFromHTML, deflateCompress } from './utils.js'
import { processRelationEndpointData } from './waysEndpoint.js'
import { processRelationWaysData } from './waysLayer.js'
import { routeData } from './waysRoute.js'

const busAnimationElement = document.getElementById('bus-animation')
const loadRelationForm = document.getElementById('load-relation-form')
const loadRelationBtn = loadRelationForm.querySelector('button[type=submit]')
const relationIdElements = document.querySelectorAll('.view .relation-id')
const relationUrlElements = document.querySelectorAll('.view .relation-url')
const editBackBtn = document.querySelector('#view-edit .btn-back')
const editTags = document.getElementById('edit-tags')
const editWarnings = document.getElementById('edit-warnings')
const editSubmitBtn = document.querySelector('#view-edit .btn-next')
const sumitBackBtn = document.querySelector('#view-submit .btn-back')
const routeSummary = document.getElementById('route-summary')
const submitUploadBtn = document.querySelector('#view-submit .btn-upload')
const submitDownloadBtn = document.querySelector('#view-submit .btn-download')

export let relationId = null
let activeView = 'load'

const switchView = name => {
    const className = `view-${name}`

    document.querySelectorAll('.view').forEach(view => {
        if (view.id === className)
            view.classList.remove('d-none')
        else
            view.classList.add('d-none')
    })

    activeView = name
}

loadRelationForm.addEventListener('submit', (e) => {
    e.preventDefault()

    if (loadRelationBtn.classList.contains('is-loading'))
        return

    const relationIdInput = loadRelationForm.querySelector('input[name=relation-id]')
    relationId = parseInt(relationIdInput.value)

    relationIdInput.disabled = true
    loadRelationBtn.classList.add('btn-secondary')
    loadRelationBtn.classList.add('is-loading')
    loadRelationBtn.innerHTML = busAnimationElement.innerHTML

    for (const relationIdElement of relationIdElements)
        relationIdElement.innerText = `${relationId}`

    for (const relationUrlElement of relationUrlElements)
        relationUrlElement.href = `https://www.openstreetmap.org/relation/${relationId}`

    fetch('/query', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            relationId: relationId
        })
    })
        .then(async resp => {
            if (!resp.ok) {
                showMessage(
                    'danger',
                    `❌ Relation load failed - ${resp.status}`,
                    await resp.text()
                )
                return
            }

            return resp.json()
        })
        .then(data => {
            if (!data)
                return

            processFetchRelationData(data)
        })
        .catch(error => {
            console.error(error)
            showMessage(
                'danger',
                '❌ Relation load failed',
                error
            )
        })
        .finally(() => {
            relationIdInput.disabled = false
            loadRelationBtn.classList.remove('btn-secondary')
            loadRelationBtn.classList.remove('is-loading')
            loadRelationBtn.innerHTML = 'Load'
        })
})

export const processFetchRelationData = data => {
    processRelationTags(data)
    switchView('edit')

    // order is important here
    processRelationEndpointData(data)
    processRelationWaysData(data)

    // order is not important here
    processRelationDownloadTriggers(data)
    processBusStopData(data)
}

export const processRelationTags = data => {
    const dummyDiv = document.createElement('div')

    if (data.nameOrRef)
        dummyDiv.appendChild(createElementFromHTML(`<tr><td colspan="2">${data.nameOrRef}</td></tr>`))

    const interestingTags = ['fixme', 'note', 'from', 'via', 'to', 'network', 'operator']

    for (const tag of interestingTags)
        if (data.tags[tag])
            dummyDiv.appendChild(createElementFromHTML(`<tr><td class="key">${tag}</td><td class="value">${data.tags[tag]}</td></tr>`))

    editTags.innerHTML = dummyDiv.innerHTML
}

export const processRouteWarnings = data => {
    if (activeView == 'submit')
        switchView('edit')

    editSubmitBtn.classList.add('d-none')

    editWarnings.innerHTML = ''
    let highestSeverityLevel = 0

    for (const warning of data.warnings) {
        const [severity_text, severity_level] = warning.severity
        highestSeverityLevel = Math.max(highestSeverityLevel, severity_level)

        editWarnings.appendChild(createElementFromHTML(`
        <div class="warning warning-${severity_text}">
            ${warning.message}
        </div>`))
    }

    if (highestSeverityLevel == 0)
        editSubmitBtn.classList.remove('d-none')
}

const unload = () => {
    switchView('load')

    processRelationEndpointData(null)
    processRelationWaysData(null)
    processRelationDownloadTriggers(null)
    processBusStopData(null)

    relationId = null
}

editBackBtn.onclick = unload

editSubmitBtn.onclick = () => {
    switchView('submit')
}

const styleStopName = name => {
    let styledName = ''

    for (let i = 0; i < name.length; i++) {
        const char = name.charAt(i)

        if (char >= '0' && char <= '9')
            styledName += `<span class="digit digit-${char}">${char}</span>`
        else
            styledName += char
    }

    return styledName
}

export const processRouteStops = data => {
    routeSummary.innerHTML = ''

    for (const collection of data.busStops) {
        const name = collection.platform ? collection.platform.name : collection.stop.name

        routeSummary.appendChild(createElementFromHTML(`
        <div class="route-summary-item">
            <img class="stop-icon" src="/static/img/bus_stop.webp" alt="Bus stop icon" height="28">
            <div class="stop-name">${styleStopName(name)}</div>
        </div>`))
    }

    const allItems = Array.from(routeSummary.querySelectorAll('.route-summary-item'))
    const allIcons = allItems.map(item => item.querySelector('.stop-icon'))

    for (const [index, item] of allItems.entries()) {
        item.onclick = () => {
            allItems.forEach((item, i) => {
                const icon = allIcons[i]
                if (i <= index) {
                    item.classList.add('route-summary-item-checked')
                    icon.src = '/static/img/bus_stop_check.webp'
                } else {
                    item.classList.remove('route-summary-item-checked')
                    icon.src = '/static/img/bus_stop.webp'
                }
            })
        }
    }
}

sumitBackBtn.onclick = () => {
    switchView('edit')
}

submitUploadBtn.onclick = async () => {
    submitUploadBtn.disabled = true

    fetch('/upload_osm', {
        method: 'POST',
        headers: {
            'Content-Encoding': 'deflate',
            'Content-Type': 'application/json'
        },
        body: await deflateCompress({
            relationId: relationId,
            route: routeData
        })
    })
        .then(async resp => {
            if (!resp.ok) {
                showMessage(
                    'danger',
                    `❌ Upload failed - ${resp.status}`,
                    await resp.text()
                )
                return
            }

            return resp.json()
        })
        .then(data => {
            if (!data)
                return

            if (!data.ok) {
                showMessage(
                    'danger',
                    `❌ Upload failed - ${data.error_code}`,
                    data.error_message
                )
                return
            }

            showMessage(
                'success',
                '✅ Upload successful',
                `The changeset <a href="https://www.openstreetmap.org/changeset/${data.changeset_id}" target="_blank">${data.changeset_id}</a> has been uploaded.<br>` +
                `<br>` +
                `<i>Something broke? Use <a href="https://revert.monicz.dev/?changesets=${data.changeset_id}" target="_blank">this tool</a> to revert it.</i>`
            )
            unload()
        })
        .catch(error => {
            console.error(error)
            showMessage(
                'danger',
                '❌ Upload failed',
                error
            )
        })
        .finally(() => {
            submitUploadBtn.disabled = false
        })
}

submitDownloadBtn.onclick = async () => {
    submitDownloadBtn.disabled = true

    fetch('/download_osm_change', {
        method: 'POST',
        headers: {
            'Content-Encoding': 'deflate',
            'Content-Type': 'application/json'
        },
        body: await deflateCompress({
            relationId: relationId,
            route: routeData
        })
    })
        .then(async resp => {
            if (!resp.ok) {
                showMessage(
                    'danger',
                    `❌ Download failed - ${resp.status}`,
                    await resp.text()
                )
                return
            }

            return resp.blob()
        })
        .then(blob => {
            if (!blob)
                return

            const a = document.createElement('a')
            a.href = URL.createObjectURL(blob)
            a.download = `relatify_${relationId}_${new Date().toISOString().replace(/:/g, '_')}.osc`
            a.click()
        })
        .catch(error => {
            console.error(error)
            showMessage(
                'danger',
                '❌ Download failed',
                error
            )
        })
        .finally(() => {
            submitDownloadBtn.disabled = false
        })
}
