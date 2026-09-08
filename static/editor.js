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

    /*
     * External web link.
     */
    document.getElementById("link-btn").addEventListener("click", () => {
        const url = window.prompt("Enter the web address:");

        if (!url) return;

        editor.focus();

        document.execCommand(
            "createLink",
            false,
            url
        );
    });

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

    ensureTrailingParagraph();

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
        ensureTrailingParagraph();
        hidden.value = editor.innerHTML;
    });
})();
