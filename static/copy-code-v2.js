document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".document pre").forEach((pre) => {
        pre.style.position = "relative";
        pre.style.paddingTop = "48px";

        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Copy";
        button.setAttribute("aria-label", "Copy code to clipboard");

        Object.assign(button.style, {
            position: "absolute",
            top: "10px",
            right: "10px",
            padding: "5px 10px",
            border: "1px solid rgba(255,255,255,0.25)",
            borderRadius: "6px",
            background: "rgba(255,255,255,0.10)",
            color: "#ffffff",
            fontSize: "13px",
            cursor: "pointer"
        });

        button.addEventListener("mouseenter", () => {
            button.style.background = "rgba(255,255,255,0.20)";
        });

        button.addEventListener("mouseleave", () => {
            button.style.background = "rgba(255,255,255,0.10)";
        });

        button.addEventListener("click", async () => {
            try {
                const clone = pre.cloneNode(true);

                clone.querySelectorAll("button").forEach((b) => b.remove());

                const text = clone.innerText.trim();

                await navigator.clipboard.writeText(text);

                button.textContent = "Copied!";

                setTimeout(() => {
                    button.textContent = "Copy";
                }, 1500);
            } catch (error) {
                button.textContent = "Failed";

                setTimeout(() => {
                    button.textContent = "Copy";
                }, 1500);
            }
        });

        pre.appendChild(button);
    });
});
