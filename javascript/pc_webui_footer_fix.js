/**
 * Force the global WebUI #footer out of position:fixed / full-height .wrap so it stays
 * at the end of the layout and does not paint over Prompt Composer (Gradio 4 + themes).
 */
(function () {
    'use strict';

    var debounceTimer = null;

    function normalizeFooter() {
        var el = document.getElementById('footer');
        if (!el) return;

        el.style.setProperty('position', 'static', 'important');
        el.style.setProperty('height', 'auto', 'important');
        el.style.setProperty('min-height', '0', 'important');
        el.style.setProperty('max-height', 'none', 'important');
        el.style.setProperty('left', 'auto', 'important');
        el.style.setProperty('right', 'auto', 'important');
        el.style.setProperty('bottom', 'auto', 'important');
        el.style.setProperty('top', 'auto', 'important');
        el.style.setProperty('z-index', 'auto', 'important');
        el.style.setProperty('flex-grow', '0', 'important');
        el.style.setProperty('flex-shrink', '0', 'important');

        var wrap = el.querySelector('.wrap');
        if (wrap) {
            wrap.style.setProperty('height', 'auto', 'important');
            wrap.style.setProperty('min-height', '0', 'important');
            wrap.style.setProperty('max-height', 'none', 'important');
        }
    }

    function schedule() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            normalizeFooter();
        }, 30);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', schedule);
    } else {
        schedule();
    }

    try {
        var obs = new MutationObserver(schedule);
        obs.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* ignore */ }
})();
