/**
 * If #footer is nested inside #tabs (Gradio can re-parent long layouts), it may paint
 * over Prompt Composer blocks. Keep it as the next sibling of #tabs under their parent.
 */
(function () {
    'use strict';

    var debounceTimer = null;
    var domObserver = null;

    function stopDomObserver() {
        if (!domObserver) return;
        try {
            domObserver.disconnect();
        } catch (e) { /* ignore */ }
        domObserver = null;
    }

    function placeFooterAfterTabs() {
        var footer = document.getElementById('footer');
        var tabs = document.getElementById('tabs');
        if (!footer || !tabs) return false;
        var parent = tabs.parentElement;
        if (!parent || !parent.contains(footer)) return false;
        if (footer.parentElement === parent && tabs.nextElementSibling === footer) {
            stopDomObserver();
            return true;
        }
        if (tabs.contains(footer)) {
            try {
                parent.insertBefore(footer, tabs.nextSibling);
            } catch (e) { /* ignore */ }
        }
        if (footer.parentElement === parent && tabs.nextElementSibling === footer) {
            stopDomObserver();
            return true;
        }
        return false;
    }

    function schedule() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            placeFooterAfterTabs();
        }, 120);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', schedule);
    } else {
        schedule();
    }

    setTimeout(placeFooterAfterTabs, 400);
    setTimeout(placeFooterAfterTabs, 2000);

    try {
        domObserver = new MutationObserver(schedule);
        domObserver.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* ignore */ }

    if (typeof onUiUpdate === 'function') {
        onUiUpdate(function () {
            if (!domObserver) return;
            schedule();
        });
    }
})();
