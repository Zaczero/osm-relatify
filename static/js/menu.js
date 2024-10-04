import { busStopData, processBusStopData } from "./busStopsLayer.js"
import { downloadHistoryData, processRelationDownloadTriggers } from "./downloadTriggers.js"
import { map } from "./map.js"
import { showMessage } from "./messageBox.js"
import { createElementFromHTML, deflateCompress, getBusCollectionName } from "./utils.js"
import { processRelationEndpointData } from "./waysEndpoint.js"
import { processRelationWaysData, removeMembersList, waysData } from "./waysLayer.js"
import { routeData } from "./waysRoute.js"

const busAnimationElement = document.getElementById("bus-animation")
const loadRelationForm = document.getElementById("load-relation-form")
const loadRelationBtn = loadRelationForm.querySelector("button[type=submit]")
const relationIdInput = loadRelationForm.querySelector("input[name=relation-id]")
const relationIdElements = document.querySelectorAll(".view .relation-id")
const relationUrlElements = document.querySelectorAll(".view .relation-url")
const editBackBtn = document.querySelector("#view-edit .btn-back")
const editReloadBtn = document.querySelector("#view-edit .btn-reload")
const editTags = document.getElementById("edit-tags")
const editWarnings = document.getElementById("edit-warnings")
const editSubmitBtn = document.querySelector("#view-edit .btn-next")
const sumitBackBtn = document.querySelector("#view-submit .btn-back")
const routeSummary = document.getElementById("route-summary")
const submitUploadBtn = document.querySelector("#view-submit .btn-upload")
const submitDownloadBtn = document.querySelector("#view-submit .btn-download")

export let relationId = null
export let relationTags = null
let activeView = "load"

const switchView = (name) => {
    const className = `view-${name}`

    for (const view of document.querySelectorAll(".view")) {
        if (view.id === className) view.classList.remove("d-none")
        else view.classList.add("d-none")
    }

    activeView = name
}

relationIdInput.focus()

relationIdInput.addEventListener("input", (e) => {
    const match = relationIdInput.value.match(/\d+/)
    e.target.value = match !== null ? match[0] : ""
})

loadRelationForm.addEventListener("submit", (e) => {
    e.preventDefault()

    if (loadRelationBtn.classList.contains("is-loading")) return

    relationId = parseInt(relationIdInput.value)
    relationIdInput.disabled = true
    loadRelationBtn.classList.add("btn-secondary")
    loadRelationBtn.classList.add("is-loading")
    loadRelationBtn.innerHTML = busAnimationElement.innerHTML

    for (const relationIdElement of relationIdElements) relationIdElement.innerText = `${relationId}`

    for (const relationUrlElement of relationUrlElements)
        relationUrlElement.href = `https://www.openstreetmap.org/relation/${relationId}`

    fetch("/query", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            relationId: relationId,
        }),
    })
        .then(async (resp) => {
            if (!resp.ok) {
                showMessage("danger", `❌ Relation load failed - ${resp.status}`, await resp.text())
                return
            }

            return resp.json()
        })
        .then((data) => {
            if (!data) return

            processFetchRelationData(data)
        })
        .catch((error) => {
            console.error(error)
            showMessage("danger", "❌ Relation load failed", error)
        })
        .finally(() => {
            relationIdInput.disabled = false
            loadRelationBtn.classList.remove("btn-secondary")
            loadRelationBtn.classList.remove("is-loading")
            loadRelationBtn.innerHTML = "Load"
        })
})

export const processFetchRelationData = (data) => {
    processRelationTags(data)
    switchView("edit")

    // order is important here
    processRelationEndpointData(data)
    processRelationWaysData(data)

    // order is not important here
    processRelationDownloadTriggers(data)
    processBusStopData(data)
}

export const processRelationTags = (data) => {
    relationTags = data.tags

    const dummyDiv = document.createElement("div")

    if (data.nameOrRef) dummyDiv.appendChild(createElementFromHTML(`<tr><td colspan="2">${data.nameOrRef}</td></tr>`))

    const interestingTags = ["fixme", "note", "from", "via", "to", "network", "operator", "roundtrip"]

    for (const tag of interestingTags)
        if (data.tags[tag])
            dummyDiv.appendChild(
                createElementFromHTML(`<tr><td class="key">${tag}</td><td class="value">${data.tags[tag]}</td></tr>`),
            )

    editTags.innerHTML = dummyDiv.innerHTML
}

export const processRouteWarnings = (data) => {
    if (activeView === "submit") switchView("edit")

    editSubmitBtn.classList.add("d-none")

    editWarnings.innerHTML = ""
    let highestSeverityLevel = 0

    for (const warning of data.warnings) {
        const severityLevel = warning.severity
        const severityText = {
            0: "LOW",
            1: "HIGH",
            10: "UNCHANGED",
        }[severityLevel]

        highestSeverityLevel = Math.max(highestSeverityLevel, severityLevel)

        if (warning.message === "Some ways are not used") {
            const child = createElementFromHTML(`
            <div class="warning warning-${severityText}">
                <div class="warning-message">${warning.message}</div>
                <div class="btn-group-vertical ms-2">
                    <button class="btn primary btn-primary">Show me</button>
                    <button class="btn secondary btn-outline-danger">Deselect all</button>
                </div>
            </div>`)

            child.querySelector("button.primary").onclick = () => {
                // show me
                const wayId = warning.extra[0]
                const way = waysData[wayId]
                map.setView(way.midpoint, 19)
            }

            child.querySelector("button.secondary").onclick = () => {
                // deselect all
                removeMembersList(warning.extra)
            }

            editWarnings.appendChild(child)
        } else if (warning.message === "Some stops are far away" || warning.message === "Some stops are not reached") {
            const child = createElementFromHTML(`
            <div class="warning warning-${severityText}">
                <div class="warning-message">${warning.message}</div>
                <div class="btn-group-vertical ms-2">
                    <button class="btn primary btn-primary">Show me</button>
                </div>
            </div>`)

            child.querySelector("button.primary").onclick = () => {
                // show me
                const stopId = warning.extra[0]
                const stop = busStopData.find(
                    (c) => (c.platform && c.platform.id === stopId) || (c.stop && c.stop.id === stopId),
                )

                if (stop)
                    if (stop.platform) map.setView(stop.platform.latLng, 19)
                    else map.setView(stop.stop.latLng, 19)
            }

            editWarnings.appendChild(child)
        } else {
            editWarnings.appendChild(
                createElementFromHTML(`
            <div class="warning warning-${severityText}">
                <div class="warning-message">${warning.message}</div>
            </div>`),
            )
        }
    }

    editSubmitBtn.classList.toggle("mt-2", data.warnings.length > 0)

    if (highestSeverityLevel === 0) editSubmitBtn.classList.remove("d-none")
}

const unload = () => {
    switchView("load")

    processRelationEndpointData(null)
    processRelationWaysData(null)
    processRelationDownloadTriggers(null)
    processBusStopData(null)

    relationId = null
}

editBackBtn.onclick = unload

editReloadBtn.onclick = async () => {
    editBackBtn.disabled = true
    editReloadBtn.disabled = true

    const defaultInnerText = editReloadBtn.innerText
    editReloadBtn.innerText = "Reloading..."

    fetch("/query", {
        method: "POST",
        headers: {
            "Content-Encoding": "deflate",
            "Content-Type": "application/json",
        },
        body: await deflateCompress({
            relationId: relationId,
            downloadHistory: downloadHistoryData,
            downloadTargets: [],
            reload: true,
        }),
    })
        .then(async (resp) => {
            if (!resp.ok) {
                showMessage("danger", `❌ Relation reload failed - ${resp.status}`, await resp.text())
                return
            }

            return resp.json()
        })
        .then((data) => {
            processFetchRelationData(data)
        })
        .catch((error) => {
            console.error(error)
            showMessage("danger", "❌ Relation reload failed", error)
        })
        .finally(() => {
            editReloadBtn.innerText = defaultInnerText

            editBackBtn.disabled = false
            editReloadBtn.disabled = false
        })
}

editSubmitBtn.onclick = () => {
    switchView("submit")
}

const styleStopName = (name) => {
    return name.replace(/^(?:\d+)|(?:\d+)$/, (match) => {
        return match
            .split("")
            .map((d) => `<span class="digit digit-${d}">${d}</span>`)
            .join("")
    })
}

export const processRouteStops = (data) => {
    routeSummary.innerHTML = ""

    for (const collection of data.busStops) {
        const isPlatform = collection.platform != null
        const isStop = collection.stop != null

        routeSummary.appendChild(
            createElementFromHTML(`
        <div class="route-summary-item">
            <img class="stop-icon" src="/static/img/bus_stop.webp" alt="Bus stop icon" height="28">
            <div class="stop-name">${styleStopName(getBusCollectionName(collection))}</div>
            <div class="stop-info">
                ${
                    isPlatform
                        ? `<a class="stop-info-platform link-underline link-underline-opacity-0 link-underline-opacity-100-hover"
                    title="This stop has a platform"
                    href="https://www.openstreetmap.org/${collection.platform.type}/${collection.platform.id}"
                    target="_blank">P</a>`
                        : ""
                }<!--
                -->${
                    isStop
                        ? `<a class="stop-info-stop link-underline link-underline-opacity-0 link-underline-opacity-100-hover"
                    title="This stop has a stopping position"
                    href="https://www.openstreetmap.org/${collection.stop.type}/${collection.stop.id}"
                    target="_blank">S</a>`
                        : ""
                }
            </div>
        </div>`),
        )
    }

    const allItems = Array.from(routeSummary.querySelectorAll(".route-summary-item"))
    const allIcons = allItems.map((item) => item.querySelector(".stop-icon"))

    for (const [outerIndex, outerItem] of allItems.entries()) {
        outerItem.onclick = (e) => {
            e.stopPropagation()

            if (e.target.tagName === "A") return

            for (const [index, item] of allItems.entries()) {
                if (index <= outerIndex) {
                    item.classList.add("route-summary-item-checked")
                    allIcons[index].src = "/static/img/bus_stop_check.webp"
                } else {
                    item.classList.remove("route-summary-item-checked")
                    allIcons[index].src = "/static/img/bus_stop.webp"
                }
            }
        }
    }
}

sumitBackBtn.onclick = () => {
    switchView("edit")
}

submitUploadBtn.onclick = async () => {
    submitUploadBtn.disabled = true

    fetch("/upload_osm", {
        method: "POST",
        headers: {
            "Content-Encoding": "deflate",
            "Content-Type": "application/json",
        },
        body: await deflateCompress({
            relationId: relationId,
            route: routeData,
            tags: relationTags,
        }),
    })
        .then(async (resp) => {
            if (!resp.ok) {
                showMessage("danger", `❌ Upload failed - ${resp.status}`, await resp.text())
                return
            }

            return resp.json()
        })
        .then((data) => {
            if (!data) return

            if (!data.ok) {
                showMessage("danger", `❌ Upload failed - ${data.error_code}`, data.error_message)
                return
            }

            showMessage(
                "success",
                "✅ Upload successful",
                `The changeset <a href="https://www.openstreetmap.org/changeset/${data.changeset_id}" target="_blank">${data.changeset_id}</a> has been uploaded.<br>` +
                    `<br>` +
                    `<i>Something broke? Use <a href="https://revert.monicz.dev/?changesets=${data.changeset_id}" target="_blank">this tool</a> to revert it.</i>`,
            )
            unload()
        })
        .catch((error) => {
            console.error(error)
            showMessage("danger", "❌ Upload failed", error)
        })
        .finally(() => {
            submitUploadBtn.disabled = false
        })
}

submitDownloadBtn.onclick = async () => {
    submitDownloadBtn.disabled = true

    fetch("/download_osm_change", {
        method: "POST",
        headers: {
            "Content-Encoding": "deflate",
            "Content-Type": "application/json",
        },
        body: await deflateCompress({
            relationId: relationId,
            route: routeData,
            tags: relationTags,
        }),
    })
        .then(async (resp) => {
            if (!resp.ok) {
                showMessage("danger", `❌ Download failed - ${resp.status}`, await resp.text())
                return
            }

            return resp.blob()
        })
        .then((blob) => {
            if (!blob) return

            const a = document.createElement("a")
            a.href = URL.createObjectURL(blob)
            a.download = `relatify_${relationId}_${new Date().toISOString().replace(/:/g, "_")}.osc`
            a.click()
        })
        .catch((error) => {
            console.error(error)
            showMessage("danger", "❌ Download failed", error)
        })
        .finally(() => {
            submitDownloadBtn.disabled = false
        })
}

// support &load=1 in query string
const urlParams = new URLSearchParams(window.location.search)
if (urlParams.get("load") === "1") loadRelationBtn.click()
