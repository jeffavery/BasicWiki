(() => {
    const editor = document.getElementById("editor");
    const hidden = document.getElementById("content_html");
    const form = document.getElementById("page-form");

    if (!editor || !hidden || !form) return;

    /*
     * Prevent toolbar clicks from destroying the current
     * text selection inside the editor.
     */
    document.querySelectorAll(".toolbar button").forEach((button) => {
        button.addEventListener("mousedown", (event) => {
            event.preventDefault();
        });
    });

    /*
     * Basic formatting.
     */
    document.querySelectorAll("[data-command]").forEach((button) => {
        button.addEventListener("click", () => {
            editor.focus();
            document.execCommand(
                button.dataset.command,
                false,
                null
            );
        });
    });

    /*
     * Heading / normal paragraph.
     */
    document.querySelectorAll("[data-block]").forEach((button) => {
        button.addEventListener("click", () => {
            editor.focus();

            document.execCommand(
                "formatBlock",
                false,
                button.dataset.block
            );
        });
    });

    /* External links and links to uploaded documents/media. */
    const linkDialog = document.getElementById("link-dialog");
    const linkUrl = document.getElementById("link-url");
    const fileInput = document.getElementById("file-input");
    const fileResults = document.getElementById("uploaded-file-results");
    const fileStatus = document.getElementById("file-upload-status");
    const applyFileLinkButton = document.getElementById("apply-file-link-btn");
    let linkRange = null;
    let selectedFile = null;

    function applyLink(url, fallbackText) {
        linkDialog.close();
        editor.focus();
        const selection = window.getSelection();
        selection.removeAllRanges();
        if (linkRange && editor.contains(linkRange.commonAncestorContainer)) selection.addRange(linkRange);
        if (selection.rangeCount && selection.toString()) {
            document.execCommand("createLink", false, url);
        } else {
            document.execCommand("insertHTML", false, `<a href="${escapeHtml(url)}">${escapeHtml(fallbackText || url)}</a>`);
        }
    }

    document.getElementById("link-btn").addEventListener("click", async () => {
        const selection = window.getSelection();
        linkRange = selection.rangeCount && editor.contains(selection.anchorNode)
            ? selection.getRangeAt(0).cloneRange() : null;
        linkUrl.value = "";
        fileStatus.textContent = "";
        selectedFile = null;
        applyFileLinkButton.disabled = true;
        linkDialog.showModal();
        await loadFiles();
        linkUrl.focus();
    });

    document.getElementById("apply-link-btn").addEventListener("click", () => {
        if (linkUrl.value) applyLink(linkUrl.value, linkUrl.value);
    });

    document.getElementById("upload-file-btn").addEventListener("click", () => fileInput.click());

    applyFileLinkButton.addEventListener("click", () => {
        if (selectedFile) applyLink(selectedFile.url, selectedFile.name);
    });

    fileInput.addEventListener("change", async () => {
        const file = fileInput.files[0];
        if (!file) return;
        fileStatus.textContent = "Uploading file...";
        const body = new FormData();
        body.append("file", file);
        try {
            const response = await fetch("/api/uploads/files", { method: "POST", body });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "File upload failed.");
            fileStatus.textContent = "File uploaded and selected.";
            await loadFiles(result.name);
        } catch (error) {
            fileStatus.textContent = error.message;
        } finally {
            fileInput.value = "";
        }
    });

    async function loadFiles(selectName = null) {
        const response = await fetch("/api/uploads/files");
        const result = await response.json();
        fileResults.innerHTML = "";
        if (!result.length) {
            fileResults.innerHTML = "<p class='muted'>No files uploaded yet.</p>";
            return;
        }
        result.forEach((file) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "wiki-link-item";
            button.textContent = file.name;
            button.addEventListener("click", () => {
                fileResults.querySelectorAll(".selected").forEach((item) => item.classList.remove("selected"));
                button.classList.add("selected");
                selectedFile = file;
                applyFileLinkButton.disabled = false;
                fileStatus.textContent = `Selected: ${file.name}`;
            });
            fileResults.appendChild(button);
            if (file.name === selectName) button.click();
        });
    }

    /*
     * CODE BLOCK
     *
     * Converts the current paragraph directly to PRE.
     *
     * If already inside a PRE, converts it back to a
     * normal paragraph.
     *
     * If the PRE is the final block in the document,
     * automatically creates a blank paragraph after it
     * so the cursor can escape the code block.
     */
    document.getElementById("code-btn").addEventListener("click", () => {
        editor.focus();

        const selection = window.getSelection();

        if (!selection.rangeCount) return;

        let node = selection.anchorNode;

        if (node && node.nodeType === Node.TEXT_NODE) {
            node = node.parentElement;
        }

        const existingPre = node ? node.closest("pre") : null;

        if (existingPre && editor.contains(existingPre)) {
            document.execCommand(
                "formatBlock",
                false,
                "p"
            );

            return;
        }

        document.execCommand(
            "formatBlock",
            false,
            "pre"
        );

        /*
         * Find the PRE we just created.
         */
        const newSelection = window.getSelection();

        if (!newSelection.rangeCount) return;

        let currentNode = newSelection.anchorNode;

        if (currentNode && currentNode.nodeType === Node.TEXT_NODE) {
            currentNode = currentNode.parentElement;
        }

        const newPre = currentNode ? currentNode.closest("pre") : null;

        if (!newPre || !editor.contains(newPre)) return;

        /*
         * If there is nothing editable after the code block,
         * create a normal blank paragraph.
         */
        if (!newPre.nextElementSibling) {
            const paragraph = document.createElement("p");
            paragraph.innerHTML = "<br>";

            newPre.insertAdjacentElement(
                "afterend",
                paragraph
            );
        }
    });

    /*
     * Also make sure an existing final PRE never traps
     * the cursor when an old page is opened for editing.
     */
    function ensureTrailingParagraph() {
        const last = editor.lastElementChild;

        if (last && last.tagName === "PRE") {
            const paragraph = document.createElement("p");
            paragraph.innerHTML = "<br>";
            editor.appendChild(paragraph);
        }
    }

    /*
     * Browsers do not agree on the block created by Enter in a
     * contenteditable area. Some create DIVs, but the server's HTML
     * allowlist intentionally keeps wiki content to semantic paragraphs.
     * Normalize only top-level editor DIVs so an empty line remains
     * <p><br></p> after sanitizing and rendering.
     */
    function normalizeParagraphs() {
        Array.from(editor.children).forEach((element) => {
            if (element.tagName !== "DIV") return;
            if (element.querySelector("p, div, h1, h2, h3, ul, ol, pre, blockquote, hr")) return;

            const paragraph = document.createElement("p");

            while (element.firstChild) {
                paragraph.appendChild(element.firstChild);
            }

            if (!paragraph.hasChildNodes()) {
                paragraph.innerHTML = "<br>";
            }

            element.replaceWith(paragraph);
        });
    }

    ensureTrailingParagraph();

    /*
     * Image uploads. Preserve the caret while the native file picker and
     * upload are active, then insert the served image at that exact point.
     */
    const imageButton = document.getElementById("image-btn");
    const imageInput = document.getElementById("image-input");
    const uploadStatus = document.getElementById("image-upload-status");
    let imageRange = null;

    imageButton.addEventListener("click", () => {
        const selection = window.getSelection();
        if (selection.rangeCount && editor.contains(selection.anchorNode)) {
            imageRange = selection.getRangeAt(0).cloneRange();
        } else {
            imageRange = null;
        }
        imageInput.click();
    });

    imageInput.addEventListener("change", async () => {
        const file = imageInput.files[0];
        if (!file) return;

        imageButton.disabled = true;
        uploadStatus.className = "upload-status active";
        uploadStatus.textContent = "Uploading image...";

        try {
            const body = new FormData();
            body.append("image", file);
            const response = await fetch("/api/uploads/images", { method: "POST", body });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Image upload failed.");

            const image = document.createElement("img");
            image.src = result.url;
            image.alt = file.name.replace(/\.[^.]+$/, "");

            editor.focus();
            const selection = window.getSelection();
            selection.removeAllRanges();
            if (imageRange && editor.contains(imageRange.commonAncestorContainer)) {
                selection.addRange(imageRange);
            } else {
                const range = document.createRange();
                range.selectNodeContents(editor);
                range.collapse(false);
                selection.addRange(range);
            }

            const range = selection.getRangeAt(0);
            range.deleteContents();
            range.insertNode(image);
            range.setStartAfter(image);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);

            uploadStatus.className = "upload-status active success";
            uploadStatus.textContent = "Image uploaded and inserted.";
        } catch (error) {
            uploadStatus.className = "upload-status active error-text";
            uploadStatus.textContent = error.message;
        } finally {
            imageButton.disabled = false;
            imageInput.value = "";
        }
    });

    /*
     * Internal wiki links.
     */
    const dialog =
        document.getElementById("wiki-link-dialog");

    const search =
        document.getElementById("wiki-link-search");

    const results =
        document.getElementById("wiki-link-results");

    let savedRange = null;

    document
        .getElementById("wiki-link-btn")
        .addEventListener("click", async () => {

            const selection = window.getSelection();

            if (selection.rangeCount) {
                savedRange =
                    selection.getRangeAt(0).cloneRange();
            }

            search.value = "";
            results.innerHTML = "";

            dialog.showModal();
            search.focus();

            await loadPages("");
        });

    search.addEventListener("input", () => {
        loadPages(search.value);
    });

    async function loadPages(query) {
        const response = await fetch(
            `/api/pages?q=${encodeURIComponent(query)}`
        );

        const pages = await response.json();

        results.innerHTML = "";

        if (!pages.length) {
            results.innerHTML =
                "<p class='muted'>No pages found.</p>";

            return;
        }

        pages.forEach((page) => {
            const button =
                document.createElement("button");

            button.type = "button";
            button.className = "wiki-link-item";
            button.textContent = page.title;

            button.addEventListener("click", () => {
                dialog.close();
                editor.focus();

                const selection =
                    window.getSelection();

                selection.removeAllRanges();

                if (savedRange) {
                    selection.addRange(savedRange);
                }

                const selectedText =
                    selection.toString();

                if (selectedText) {
                    document.execCommand(
                        "createLink",
                        false,
                        page.url
                    );
                } else {
                    document.execCommand(
                        "insertHTML",
                        false,
                        `<a href="${page.url}">${escapeHtml(page.title)}</a>`
                    );
                }
            });

            results.appendChild(button);
        });
    }

    function escapeHtml(value) {
        return value
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    /*
     * Save exactly what is visible in the editor.
     */
    form.addEventListener("submit", () => {
        normalizeParagraphs();
        ensureTrailingParagraph();
        hidden.value = editor.innerHTML;
    });
})();
