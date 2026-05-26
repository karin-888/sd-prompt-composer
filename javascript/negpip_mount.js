/**
 * Mirror NegPiP (sd-webui-negpip) under Prompt Composer "自動整形".
 * Clones only the NegPiP accordion (not sibling scripts). Syncs Active state with txt2img.
 */
(function () {
    'use strict';

    var retryCount = 0;
    var debounceTimer = null;
    var syncObserver = null;

    function appRoot() {
        return document.getElementById('gradio-app') || document.body;
    }

    function findNegpipAccordion(container) {
        if (!container) return null;
        var accordions = container.querySelectorAll('.input-accordion-m');
        for (var i = 0; i < accordions.length; i++) {
            var acc = accordions[i];
            var labelWrap = acc.querySelector('.label-wrap');
            var text = (labelWrap ? labelWrap.textContent : acc.textContent) || '';
            if (/NegPiP/i.test(text)) return acc;
        }
        return null;
    }

    function suffixElementIds(root, suffix) {
        root.querySelectorAll('[id]').forEach(function (el) {
            el.id = el.id + suffix;
        });
        root.querySelectorAll('label[for]').forEach(function (el) {
            var target = el.getAttribute('for');
            if (target) el.setAttribute('for', target + suffix);
        });
    }

    function getGradioCheckboxInput(accordion) {
        if (!accordion || !accordion.id) return null;
        var wrap = appRoot().querySelector('#' + accordion.id + '-checkbox');
        return wrap ? wrap.querySelector('input[type="checkbox"]') : null;
    }

    function getVisibleCheckbox(accordion) {
        if (!accordion) return null;
        return accordion.querySelector('.input-accordion-checkbox')
            || accordion.querySelector('input[type="checkbox"]');
    }

    function setCheckboxInput(input, checked) {
        if (!input || input.checked === checked) return;
        input.checked = checked;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function replaceWithFreshCheckbox(oldInput) {
        if (!oldInput || !oldInput.parentNode) return oldInput;
        var fresh = document.createElement('input');
        fresh.type = 'checkbox';
        fresh.className = oldInput.className;
        fresh.id = oldInput.id;
        fresh.checked = oldInput.checked;
        oldInput.parentNode.replaceChild(fresh, oldInput);
        return fresh;
    }

    function stripCloneGradioInputs(cloneRoot) {
        cloneRoot.querySelectorAll('[id$="-checkbox"]').forEach(function (wrap) {
            wrap.querySelectorAll('input, textarea, select').forEach(function (el) {
                el.remove();
            });
        });
    }

    function bindNegpipSync(sourceAcc, cloneAcc) {
        if (!sourceAcc || !cloneAcc) return;

        var srcGradio = getGradioCheckboxInput(sourceAcc);
        var cloneVis = getVisibleCheckbox(cloneAcc);
        cloneVis = replaceWithFreshCheckbox(cloneVis);

        var syncing = false;

        function syncCloneFromSource() {
            if (syncing || !srcGradio || !cloneVis) return;
            syncing = true;
            cloneVis.checked = srcGradio.checked;
            syncing = false;
        }

        function syncSourceFromClone() {
            if (syncing || !srcGradio || !cloneVis) return;
            syncing = true;
            setCheckboxInput(srcGradio, cloneVis.checked);
            var srcVis = getVisibleCheckbox(sourceAcc);
            if (srcVis && srcVis !== srcGradio) {
                srcVis.checked = cloneVis.checked;
            }
            if (typeof inputAccordionChecked === 'function') {
                try {
                    inputAccordionChecked(sourceAcc.id, cloneVis.checked);
                } catch (err) { /* ignore */ }
            }
            syncing = false;
        }

        cloneVis.addEventListener('click', function (event) {
            event.stopPropagation();
        });
        cloneVis.addEventListener('input', syncSourceFromClone);
        cloneVis.addEventListener('change', syncSourceFromClone);

        if (srcGradio) {
            srcGradio.addEventListener('input', syncCloneFromSource);
            srcGradio.addEventListener('change', syncCloneFromSource);
            try {
                new MutationObserver(syncCloneFromSource).observe(srcGradio, {
                    attributes: true,
                    attributeFilter: ['checked'],
                });
            } catch (err) { /* ignore */ }
        }

        var srcVis = getVisibleCheckbox(sourceAcc);
        if (srcVis && srcVis !== srcGradio) {
            srcVis.addEventListener('input', syncCloneFromSource);
            srcVis.addEventListener('change', syncCloneFromSource);
        }

        syncCloneFromSource();

        var srcToggle = sourceAcc.querySelector('#switch_default');
        var cloneToggle = cloneAcc.querySelector('[id^="switch_default"]');
        if (srcToggle && cloneToggle) {
            cloneToggle.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                srcToggle.click();
                setTimeout(function () {
                    cloneToggle.textContent = srcToggle.textContent;
                    cloneToggle.value = srcToggle.value;
                }, 150);
            });
        }
    }

    function mountNegpip() {
        var mount = document.getElementById('pc_negpip_mount');
        if (!mount) return false;

        var container = appRoot().querySelector('#txt2img_script_container');
        var sourceAcc = findNegpipAccordion(container);
        if (!sourceAcc) return false;

        var sourceId = sourceAcc.id || '';
        var existingCount = mount.querySelectorAll('.input-accordion-m').length;
        if (mount.dataset.mounted === '1' && mount.dataset.sourceId === sourceId && mount.firstElementChild) {
            if (existingCount === 1) return true;
            mount.innerHTML = '';
            mount.dataset.mounted = '';
        }

        mount.innerHTML = '';
        var cloneAcc = sourceAcc.cloneNode(true);
        cloneAcc.classList.add('pc-negpip-clone');
        suffixElementIds(cloneAcc, '-pc');
        stripCloneGradioInputs(cloneAcc);
        mount.appendChild(cloneAcc);
        bindNegpipSync(sourceAcc, cloneAcc);

        mount.dataset.mounted = '1';
        mount.dataset.sourceId = sourceId;

        console.log('[Prompt Composer] NegPiP mirrored under auto-format (synced with txt2img)');
        return true;
    }

    function scheduleMount() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            if (mountNegpip()) return;
            if (retryCount < 40) {
                retryCount++;
                setTimeout(scheduleMount, 500);
            }
        }, 80);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleMount);
    } else {
        scheduleMount();
    }

    try {
        if (syncObserver) syncObserver.disconnect();
        syncObserver = new MutationObserver(function () {
            var mount = document.getElementById('pc_negpip_mount');
            if (!mount) return;
            var container = appRoot().querySelector('#txt2img_script_container');
            var sourceAcc = findNegpipAccordion(container);
            if (!sourceAcc) return;
            var sourceId = sourceAcc.id || '';
            if (mount.dataset.sourceId && mount.dataset.sourceId !== sourceId) {
                mount.dataset.mounted = '';
                mount.innerHTML = '';
            }
            scheduleMount();
        });
        syncObserver.observe(document.documentElement, { childList: true, subtree: true });
    } catch (err) { /* ignore */ }
})();
