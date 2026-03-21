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

        el.style.setProperty('display', 'block', 'important');
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

        /* Inner Gradio 4 wrapper (div.prose.gradio-html) — this is what overlaps blocks */
        var prose = el.querySelectorAll('.prose');
        for (var j = 0; j < prose.length; j++) {
            var p = prose[j];
            p.style.setProperty('position', 'static', 'important');
            p.style.setProperty('top', 'auto', 'important');
            p.style.setProperty('bottom', 'auto', 'important');
            p.style.setProperty('left', 'auto', 'important');
            p.style.setProperty('right', 'auto', 'important');
            p.style.setProperty('height', 'auto', 'important');
            p.style.setProperty('min-height', '0', 'important');
            p.style.setProperty('max-height', 'none', 'important');
            p.style.setProperty('width', '100%', 'important');
            p.style.setProperty('transform', 'none', 'important');
            p.style.setProperty('z-index', 'auto', 'important');
            p.style.setProperty('flex', 'none', 'important');
            p.style.setProperty('display', 'block', 'important');
        }

        var vers = el.querySelector('.versions');
        if (vers) {
            vers.style.setProperty('display', 'block', 'important');
            vers.style.setProperty('width', '100%', 'important');
        }
    }

    function normalizeProseVersionBar() {
        /* If #footer was not used, still fix any prose that wraps footer.html .versions */
        var bars = document.querySelectorAll('div.prose.gradio-html');
        for (var i = 0; i < bars.length; i++) {
            var node = bars[i];
            if (!node.querySelector || !node.querySelector('.versions')) continue;
            if (!node.textContent || node.textContent.indexOf('checkpoint:') === -1) continue;
            node.style.setProperty('position', 'static', 'important');
            node.style.setProperty('transform', 'none', 'important');
            node.style.setProperty('z-index', 'auto', 'important');
            node.style.setProperty('height', 'auto', 'important');
            node.style.setProperty('width', '100%', 'important');
            node.style.setProperty('display', 'block', 'important');
        }
    }

    function run() {
        relocateFooter();
        normalizeFooter();
        normalizeProseVersionBar();
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
