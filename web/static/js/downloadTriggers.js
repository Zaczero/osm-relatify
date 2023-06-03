import { hideDownloadBar, showDownloadBar } from "./map.js"
import { processFetchRelationData, relationId } from "./menu.js"
import { deflateCompress } from "./utils.js"

export let downloadHistoryData = null
export let downloadTriggersData = null
let scheduledCells = []
let downloadingCells = []

let processDownloadTriggersAbortController = null

export function processRelationDownloadTriggers(fetchData) {
    if (fetchData) {
        downloadHistoryData = fetchData.downloadHistory
        downloadTriggersData = fetchData.downloadTriggers

        if (!fetchData.fetchMerge) {
            if (processDownloadTriggersAbortController) {
                processDownloadTriggersAbortController.abort()
                processDownloadTriggersAbortController = null
            }

            scheduledCells = []
            downloadingCells = []
        }
    }
    else {
        if (processDownloadTriggersAbortController) {
            processDownloadTriggersAbortController.abort()
            processDownloadTriggersAbortController = null
        }

        downloadHistoryData = null
        downloadTriggersData = null
        scheduledCells = []
        downloadingCells = []
    }
}

export const downloadTrigger = id => {
    if (downloadTriggersData && downloadTriggersData[id]) {
        const newScheduledCells = downloadTriggersData[id].filter(cell => !downloadingCells.includes(cell))
        if (newScheduledCells.length > 0) {
            scheduledCells = scheduledCells.concat(newScheduledCells)
            processDownloadTriggers()
        }
    }
}

export const processDownloadTriggers = async (_retrying = false) => {
    if (_retrying) {
        if (downloadingCells.length === 0)
            return
    }
    else {
        if (downloadingCells.length > 0 || scheduledCells.length === 0)
            return

        downloadingCells = scheduledCells
        scheduledCells = []
    }

    showDownloadBar()

    processDownloadTriggersAbortController = new AbortController()

    fetch('/query', {
        method: 'POST',
        headers: {
            'Content-Encoding': 'deflate',
            'Content-Type': 'application/json'
        },
        body: await deflateCompress({
            relationId: relationId,
            downloadHistory: downloadHistoryData,
            downloadTargets: downloadingCells
        }),
        signal: processDownloadTriggersAbortController.signal
    })
        .then(resp => {
            if (!resp.ok) {
                console.error(resp)
                throw new Error('HTTP error')
            }

            return resp.json()
        })
        .then(data => {
            processFetchRelationData(data)

            downloadingCells = []

            if (scheduledCells.length > 0)
                processDownloadTriggers()
            else
                hideDownloadBar()
        })
        .catch(error => {
            if (error.name !== 'AbortError') {
                console.error(error)
                setTimeout(() => {
                    processDownloadTriggers(true)
                }, 1000)
            }
            else {
                hideDownloadBar()
            }
        })
}
