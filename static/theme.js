(() => {
    const root = document.documentElement;
    const preference = window.matchMedia('(prefers-color-scheme: dark)');
    const storageKey = 'basicwiki-theme';
    let choice = null;

    try {
        const saved = localStorage.getItem(storageKey);
        if (saved === 'light' || saved === 'dark') choice = saved;
    } catch (_) {}

    function applyTheme() {
        const theme = choice || (preference.matches ? 'dark' : 'light');
        root.dataset.theme = theme;
        root.style.colorScheme = theme;

        const button = document.getElementById('theme-toggle');
        if (button) {
            const dark = theme === 'dark';
            button.textContent = dark ? 'Light mode' : 'Dark mode';
            button.setAttribute('aria-pressed', String(dark));
        }
    }

    applyTheme();

    document.addEventListener('DOMContentLoaded', () => {
        applyTheme();
        document.getElementById('theme-toggle').addEventListener('click', () => {
            choice = root.dataset.theme === 'dark' ? 'light' : 'dark';
            try {
                localStorage.setItem(storageKey, choice);
            } catch (_) {}
            applyTheme();
        });
    });

    preference.addEventListener('change', () => {
        if (choice === null) applyTheme();
    });

    window.addEventListener('storage', (event) => {
        if (event.key === storageKey || event.key === null) {
            choice = event.newValue === 'light' || event.newValue === 'dark'
                ? event.newValue : null;
            applyTheme();
        }
    });
})();
