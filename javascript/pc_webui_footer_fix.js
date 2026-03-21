/**
 * WebUI footer (#footer) often ends up inside .gradio-container flex layout with
 * height:100% / centered content, so API + version lines paint over the middle of
 * Prompt Composer. Move #footer to document.body (after .gradio-container) and
 * strip fixed/tall styles. Re-apply when Gradio mutates the DOM.
 */
(function () {
    'use strict';

    var debounceTimer = null;
    var intervalId = null;
    var started = false;

    function dedupeFooter() {
        var nodes = document.querySelectorAll('[id="footer"]');
        if (nodes.length <= 1) return;
        for (var i = 1; i < nodes.length; i++) {
            try {
                nodes[i].parentNode.removeChild(nodes[i]);
            } catch (e) { /* ignore */ }
        }
    }

    function relocateFooter() {
        dedupeFooter();
        var el = document.getElementById('footer');
        var body = document.body;
        var gc = document.querySelector('.gradio-container');
        if (!el || !body) return;

        /* Take footer out of Gradio flex column so it cannot sit mid-viewport */
        if (gc && gc.contains(el) && el.parentNode !== body) {
            try {
                body.appendChild(el);
            } catch (e) { /* ignore */ }
        } else if (!gc && el.parentNode !== body) {
            try {
                body.appendChild(el);
            } catch (e) { /* ignore */ }
        }
    }

    function normalizeFooter() {
        var el = document.getElementById('footer');
        if (!el) return;

        el.style.setProperty('position', 'static', 'important');
        el.style.setProperty('height', 'auto', 'important');
        el.style.setProperty('min-height', '0', 'important');
        el.style.setProperty('max-height', 'none', 'important');
        el.style.setProperty('width', '100%', 'important');
        el.style.setProperty('left', 'auto', 'important');
        el.style.setProperty('right', 'auto', 'important');
        el.style.setProperty('bottom', 'auto', 'important');
        el.style.setProperty('top', 'auto', 'important');
        el.style.setProperty('z-index', 'auto', 'important');
        el.style.setProperty('flex', 'none', 'important');
        el.style.setProperty('flex-grow', '0', 'important');
        el.style.setProperty('flex-shrink', '0', 'important');
        el.style.setProperty('transform', 'none', 'important');

        var wrap = el.querySelector('.wrap');
        if (wrap) {
            wrap.style.setProperty('height', 'auto', 'important');
            wrap.style.setProperty('min-height', '0', 'important');
            wrap.style.setProperty('max-height', 'none', 'important');
            wrap.style.setProperty('display', 'block', 'important');
            wrap.style.setProperty('flex', 'none', 'important');
        }
    }

    function run() {
        relocateFooter();
        normalizeFooter();
    }

    function schedule() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            run();
        }, 20);
    }

    function startIntervals() {
        if (started) return;
        started = true;
        /* Gradio re-renders can undo DOM move for a few seconds after load */
        var n = 0;
        intervalId = setInterval(function () {
            run();
            n += 1;
            if (n >= 40) {
                clearInterval(intervalId);
                intervalId = null;
            }
        }, 250);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            schedule();
            startIntervals();
        });
    } else {
        schedule();
        startIntervals();
    }

    try {
        var obs = new MutationObserver(schedule);
        obs.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) { /* ignore */ }
})();
