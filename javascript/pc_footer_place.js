/**
 * If #footer is nested inside #tabs (Gradio can re-parent long layouts), it may paint
 * over Prompt Composer blocks. Keep it as the next sibling of #tabs under their parent.
 */
(function () {
    'use strict';

    var debounceTimer = null;

    function placeFooterAfterTabs() {
        var footer = document.getElementById('footer');
        var tabs = document.getElementById('tabs');
        if (!footer || !tabs) return;
        var parent = tabs.parentElement;
        if (!parent || !parent.contains(footer)) return;
        if (footer.parentElement === parent && tabs.nextElementSibling === footer) return;
        if (tabs.contains(footer)) {
            try {
                parent.insertBefore(footer, tabs.nextSibling);
            } catch (e) { /* ignore */ }
        }
    }

    function schedule() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            placeFooterAfterTabs();
        }, 80);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', schedule);
    } else {
        schedule();
    }

    setTimeout(placeFooterAfterTabs, 400);
    setTimeout(placeFooterAfterTabs, 2000);

    try {
        var obs = new MutationObserver(schedule);
        obs.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* ignore */ }
})();
