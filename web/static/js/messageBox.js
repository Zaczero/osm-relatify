const messageModalSelector = document.getElementById("message-modal")
const messageModal = new bootstrap.Modal(messageModalSelector, {})
const messageModalHeader = messageModalSelector.querySelector(".modal-header")
const messageModalTitle = messageModalSelector.querySelector(".modal-title")
const messageModalBody = messageModalSelector.querySelector(".modal-body")

export const showMessage = (color, title, body) => {
    for (const className of messageModalHeader.classList) {
        if (className.startsWith("bg-")) {
            messageModalHeader.classList.remove(className)
        }
    }

    messageModalHeader.classList.add(`bg-${color}`)
    messageModalTitle.innerHTML = title
    messageModalBody.innerHTML = body
    messageModal.show()
}

window.showMessage = showMessage
