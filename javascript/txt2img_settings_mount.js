/**
 * Move txt2img settings into Prompt Composer "Generation" tab (2 columns).
 * Left: sampler / size / CFG / seed / etc.
 * Right: #txt2img_script_container (ADetailer, scripts, …)
 */
(function () {
    'use strict';

    var retryCount = 0;
    var debounceTimer = null;
    var tabSyncTimer = null;
    var syncingTabs = false;
    var domObserver = null;
    var moved = false;

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document.getElementById('gradio-app') || document.body;
    }

    function findColumnMount(root, side) {
        var id = 'pc_txt2img_settings_col_' + side;
        return root.getElementById(id)
            || root.querySelector('#pc_generation_two_col #' + id)
            || document.getElementById(id)
            || document.querySelector('#pc_generation_two_col #' + id);
    }

    function findSettingsColumn(root) {
        var el = root.querySelector('#txt2img_settings')
            || document.querySelector('#txt2img_settings');
        if (el) return el;

        var width = root.querySelector('#txt2img_width');
        if (width) {
            var node = width.parentElement;
            for (var j = 0; j < 10 && node; j++) {
                if (node.id === 'txt2img_settings') return node;
                if (node.querySelector && node.querySelector('#txt2img_cfg_scale, #txt2img_steps, #txt2img_sampling')) {
                    return node;
                }
                node = node.parentElement;
            }
        }

        var tab = root.querySelector('#tab_txt2img_generation, #txt2img_generation');
        if (tab) {
            el = tab.querySelector('#txt2img_settings');
            if (el) return el;
        }

        return null;
    }

    function unhideElement(el) {
        if (!el) return;
        el.classList.remove('hidden');
        el.removeAttribute('hidden');
        if (el.style) {
            if (el.style.display === 'none') el.style.display = '';
            if (el.style.visibility === 'hidden') el.style.visibility = '';
        }
    }

    function shouldGoRight(child, scriptContainer) {
        if (!child || child.nodeType !== Node.ELEMENT_NODE) return false;
        if (!scriptContainer) return false;
        if (child === scriptContainer) return true;
        if (child.id === 'txt2img_script_container') return true;
        if (child.contains(scriptContainer)) return true;
        return false;
    }

    function splitSettingsIntoColumns(settings, leftMount, rightMount) {
        var scriptContainer = settings.querySelector('#txt2img_script_container');
        var goRight = false;

        while (settings.firstChild) {
            var child = settings.firstChild;
            if (!goRight && shouldGoRight(child, scriptContainer)) {
                goRight = true;
            }
            if (goRight) {
                rightMount.appendChild(child);
            } else {
                leftMount.appendChild(child);
            }
        }

        if (settings.parentElement && !settings.childElementCount) {
            settings.remove();
        }
    }

    function moveSettingsToMount() {
        if (moved) return true;

        var root = appRoot();
        var leftMount = findColumnMount(root, 'left');
        var rightMount = findColumnMount(root, 'right');
        var settings = findSettingsColumn(root);
        if (!leftMount || !rightMount || !settings) return false;

        if (leftMount.querySelector('#txt2img_width, #txt2img_sampling, #txt2img_steps')
            || rightMount.querySelector('#txt2img_script_container')) {
            moved = true;
            stopDomWatch();
            leftMount.classList.remove('is-empty');
            rightMount.classList.remove('is-empty');
            unhideElement(leftMount);
            unhideElement(rightMount);
            return true;
        }

        splitSettingsIntoColumns(settings, leftMount, rightMount);

        leftMount.classList.remove('is-empty');
        rightMount.classList.remove('is-empty');
        unhideElement(leftMount);
        unhideElement(rightMount);

        moved = true;
        stopDomWatch();
        scheduleTabSync();
        console.log('[Prompt Composer] txt2img settings split into Generation 2-column layout');
        return true;
    }

    function stopDomWatch() {
        if (domObserver) {
            domObserver.disconnect();
            domObserver = null;
        }
    }

    function scheduleTabSync() {
        if (tabSyncTimer) clearTimeout(tabSyncTimer);
        tabSyncTimer = setTimeout(function () {
            tabSyncTimer = null;
            try { syncFinalPromptTabPanels(); } catch (_) { /* ignore */ }
        }, 0);
    }

    function panelIsShown(panel) {
        if (!panel) return false;
        if (panel.classList.contains('hidden') || panel.hasAttribute('hidden')) return false;
        var display = panel.style && panel.style.display;
        return display !== 'none';
    }

    function scheduleMove(delay) {
        if (moved) return;
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            if (moveSettingsToMount()) {
                retryCount = 0;
                return;
            }
            if (retryCount < 80) {
                retryCount++;
                scheduleMove(350);
            }
        }, delay == null ? 150 : delay);
    }

    function syncFinalPromptTabPanels() {
        if (syncingTabs) return;
        syncingTabs = true;
        try {
            var root = appRoot();
            var tabs = root.getElementById('pc_final_prompt_tabs');
            if (!tabs) return;
            var nav = tabs.querySelector('.tab-nav');
            if (!nav) return;
            var buttons = nav.querySelectorAll('button');
            if (!buttons.length) return;
            var panels = [];
            var children = tabs.children;
            for (var i = 0; i < children.length; i++) {
                var ch = children[i];
                if (ch === nav || ch.classList.contains('tab-nav')) continue;
                panels.push(ch);
            }
            if (!panels.length) return;
            var activeIdx = 0;
            for (var b = 0; b < buttons.length; b++) {
                if (buttons[b].classList.contains('selected') || buttons[b].getAttribute('aria-selected') === 'true') {
                    activeIdx = b;
                    break;
                }
            }
            for (var p = 0; p < panels.length; p++) {
                var panel = panels[p];
                var show = p === activeIdx;
                if (show === panelIsShown(panel)) continue;
                if (show) {
                    panel.classList.remove('hidden');
                    panel.removeAttribute('hidden');
                    panel.style.display = '';
                    panel.style.visibility = '';
                } else {
                    panel.classList.add('hidden');
                    panel.setAttribute('hidden', '');
                    panel.style.display = 'none';
                    panel.style.visibility = 'hidden';
                }
            }
        } finally {
            syncingTabs = false;
        }
    }

    function bindFinalPromptTabs() {
        var root = appRoot();
        var tabs = root.getElementById('pc_final_prompt_tabs');
        if (!tabs || tabs.dataset.pcTabBound === '1') return;
        tabs.dataset.pcTabBound = '1';
        var nav = tabs.querySelector('.tab-nav');
        if (!nav) return;
        nav.addEventListener('click', function () {
            scheduleTabSync();
        });
        scheduleTabSync();
    }

    function watchDom() {
        if (domObserver || moved) return;
        try {
            domObserver = new MutationObserver(function () {
                if (!moved) scheduleMove(250);
            });
            domObserver.observe(appRoot(), { childList: true, subtree: true });
        } catch (_) { /* ignore */ }
    }

    function init() {
        try {
            bindFinalPromptTabs();
        } catch (err) {
            console.warn('[Prompt Composer] Final prompt tab binding failed:', err);
        }
        scheduleMove(400);
        watchDom();
        setInterval(function () {
            if (!moved) scheduleMove(500);
        }, 2500);
    }

    function scheduleInit() {
        setTimeout(init, 800);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleInit);
    } else {
        scheduleInit();
    }
    if (typeof onUiLoaded === 'function') {
        onUiLoaded(scheduleInit);
    }
    if (typeof onUiUpdate === 'function') {
        onUiUpdate(function () {
            if (!moved) scheduleMove(400);
        });
    }

    window.PcTxt2imgSettingsMount = {
        sync: moveSettingsToMount,
        isMoved: function () { return moved; }
    };
})();
