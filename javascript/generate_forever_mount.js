/**
 * Mirror txt2img "Generate Forever" controls under Prompt Composer generate button.
 * Clones visible txt2img buttons when present; otherwise renders fallback buttons
 * that share window.generateOnRepeatInterval with txt2img.
 */
(function () {
    'use strict';

    var retryCount = 0;
    var debounceTimer = null;
    var stateTimer = null;
    var wasForeverActive = false;
    var lastSeenInterval = null;

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document;
    }

    function buttonLabel(btn) {
        return ((btn && btn.textContent) || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function isGenerateForeverButton(btn) {
        return /generate forever/.test(buttonLabel(btn));
    }

    function isCancelForeverButton(btn) {
        return /cancel forever|cancel generate forever/.test(buttonLabel(btn));
    }

    function findForeverButtons(scope) {
        var genBtn = null;
        var cancelBtn = null;
        if (!scope) return { genBtn: null, cancelBtn: null, row: null };

        scope.querySelectorAll('button').forEach(function (btn) {
            if (isGenerateForeverButton(btn)) genBtn = btn;
            if (isCancelForeverButton(btn)) cancelBtn = btn;
        });

        var row = null;
        if (genBtn && cancelBtn) {
            var node = genBtn.parentElement;
            while (node && node !== scope) {
                if (node.contains(cancelBtn)) {
                    row = node;
                    break;
                }
                node = node.parentElement;
            }
        } else if (genBtn || cancelBtn) {
            row = (genBtn || cancelBtn).closest('.gr-row, .form, .gap, [class*="row"]')
                || (genBtn || cancelBtn).parentElement;
        }

        return { genBtn: genBtn, cancelBtn: cancelBtn, row: row };
    }

    function findTxt2imgForeverSource() {
        var root = appRoot();
        var scopes = [
            root.querySelector('#txt2img_actions_column'),
            root.querySelector('#txt2img_generate_box') && root.querySelector('#txt2img_generate_box').parentElement,
            root.querySelector('#tab_txt2img'),
        ].filter(Boolean);

        for (var i = 0; i < scopes.length; i++) {
            var found = findForeverButtons(scopes[i]);
            if (found.genBtn || found.cancelBtn) return found;
        }
        return { genBtn: null, cancelBtn: null, row: null };
    }

    function suffixElementIds(root, suffix) {
        root.querySelectorAll('[id]').forEach(function (el) {
            el.id = el.id + suffix;
        });
    }

    function replaceWithFreshButton(oldBtn) {
        if (!oldBtn || !oldBtn.parentNode) return oldBtn;
        var fresh = oldBtn.cloneNode(true);
        fresh.removeAttribute('data-pc-forever-bound');
        oldBtn.parentNode.replaceChild(fresh, oldBtn);
        return fresh;
    }

    function bindCloneButton(cloneBtn, sourceBtn) {
        if (!cloneBtn || !sourceBtn) return;
        cloneBtn = replaceWithFreshButton(cloneBtn);
        cloneBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            sourceBtn.click();
            scheduleStateSync();
        });
    }

    function bindCloneCancelButton(cloneBtn, sourceBtn) {
        if (!cloneBtn) return;
        cloneBtn = replaceWithFreshButton(cloneBtn);
        cloneBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            cancelForeverAndSync();
            if (sourceBtn) sourceBtn.click();
        });
    }

    function cancelForeverAndSync() {
        if (window.PromptSync && typeof window.PromptSync.cancelGenerateForeverTxt2img === 'function') {
            window.PromptSync.cancelGenerateForeverTxt2img();
        } else {
            clearInterval(window.generateOnRepeatInterval);
            window.generateOnRepeatInterval = null;
            if (window.PromptSync && typeof window.PromptSync.setGenerateForeverActive === 'function') {
                window.PromptSync.setGenerateForeverActive(false);
            }
        }
        var mount = document.getElementById('pc_generate_forever_mount');
        if (mount) {
            updateForeverActiveState(mount);
        }
        scheduleStateSync();
    }

    function resetStaleForeverOnLoad() {
        if (window.PromptSync && typeof window.PromptSync.resetGenerateForeverState === 'function') {
            window.PromptSync.resetGenerateForeverState();
        } else {
            clearInterval(window.generateOnRepeatInterval);
            window.generateOnRepeatInterval = null;
        }
        lastSeenInterval = null;
    }

    function syncForeverFlagFromInterval() {
        var current = window.generateOnRepeatInterval;
        if (current === lastSeenInterval) return;
        lastSeenInterval = current;
        if (!window.PromptSync || typeof window.PromptSync.setGenerateForeverActive !== 'function') return;
        if (current != null) {
            window.PromptSync.setGenerateForeverActive(true);
        } else {
            window.PromptSync.setGenerateForeverActive(false);
        }
    }

    function ensureStatusBar(mount) {
        var bar = mount.querySelector('.pc-generate-forever-status');
        if (!bar) {
            bar = document.createElement('div');
            bar.className = 'pc-generate-forever-status';
            bar.setAttribute('aria-live', 'polite');
            bar.hidden = true;
            mount.insertBefore(bar, mount.firstChild);
        }
        return bar;
    }

    function updateForeverActiveState(mount) {
        var active = !!(window.PromptSync && window.PromptSync.isGenerateForeverActive
            ? window.PromptSync.isGenerateForeverActive()
            : window.generateOnRepeatInterval);
        mount.classList.toggle('is-forever-active', active);

        var bar = ensureStatusBar(mount);
        if (active) {
            bar.hidden = false;
            bar.textContent = '連続生成中 — Generate Forever が動作しています';
        } else {
            bar.hidden = true;
            bar.textContent = '';
        }

        mount.querySelectorAll('.pc-generate-forever-btn, button').forEach(function (btn) {
            var label = buttonLabel(btn);
            if (/generate forever/.test(label)) {
                btn.classList.toggle('is-running', active);
                btn.setAttribute('aria-pressed', active ? 'true' : 'false');
            } else if (/cancel forever|cancel generate forever/.test(label)) {
                btn.classList.toggle('is-cancel-ready', active);
            }
        });

        if (active && !wasForeverActive && window.PromptSync && typeof window.PromptSync.startPcProgressWatch === 'function') {
            window.PromptSync.startPcProgressWatch('txt2img', { foreverSession: true });
        }
        wasForeverActive = active;
    }

    function scheduleStateSync() {
        var mount = document.getElementById('pc_generate_forever_mount');
        if (!mount) return;
        updateForeverActiveState(mount);
        if (stateTimer) clearInterval(stateTimer);
        stateTimer = setInterval(function () {
            updateForeverActiveState(mount);
            var inactive = window.PromptSync && typeof window.PromptSync.isGenerateForeverActive === 'function'
                ? !window.PromptSync.isGenerateForeverActive()
                : !window.generateOnRepeatInterval;
            if (inactive) {
                clearInterval(stateTimer);
                stateTimer = null;
            }
        }, 400);
    }

    function buildFallbackButtons(mount) {
        mount.innerHTML =
            '<div class="pc-generate-forever-row">' +
            '<button type="button" class="pc-generate-forever-btn pc-generate-forever-start">∞ Generate Forever</button>' +
            '<button type="button" class="pc-generate-forever-btn pc-generate-forever-cancel">Cancel Forever</button>' +
            '</div>';

        var startBtn = mount.querySelector('.pc-generate-forever-start');
        var cancelBtn = mount.querySelector('.pc-generate-forever-cancel');

        startBtn.addEventListener('click', function (event) {
            event.preventDefault();
            if (window.PromptSync && typeof window.PromptSync.generateForeverTxt2img === 'function') {
                if (!window.PromptSync.generateForeverTxt2img()) {
                    alert('Generate Forever を開始できませんでした');
                }
            }
            scheduleStateSync();
        });

        cancelBtn.addEventListener('click', function (event) {
            event.preventDefault();
            cancelForeverAndSync();
        });
    }

    function mountGenerateForever() {
        var mount = document.getElementById('pc_generate_forever_mount');
        if (!mount) return false;

        if (mount.dataset.mounted !== '1') {
            resetStaleForeverOnLoad();
        }

        var source = findTxt2imgForeverSource();
        var sourceKey = source.row
            ? [buttonLabel(source.genBtn), buttonLabel(source.cancelBtn), source.row.childElementCount].join('|')
            : 'fallback';

        if (mount.dataset.mounted === '1' && mount.dataset.sourceKey === sourceKey && mount.firstElementChild) {
            updateForeverActiveState(mount);
            return true;
        }

        mount.innerHTML = '';
        mount.dataset.mounted = '1';
        mount.dataset.sourceKey = sourceKey;

        if (source.row) {
            var clone = source.row.cloneNode(true);
            clone.classList.add('pc-generate-forever-clone');
            suffixElementIds(clone, '-pc');
            mount.appendChild(clone);

            var cloneButtons = clone.querySelectorAll('button');
            var cloneGen = null;
            var cloneCancel = null;
            cloneButtons.forEach(function (btn) {
                if (isGenerateForeverButton(btn)) cloneGen = btn;
                if (isCancelForeverButton(btn)) cloneCancel = btn;
            });
            bindCloneButton(cloneGen, source.genBtn);
            bindCloneCancelButton(cloneCancel, source.cancelBtn);
        } else {
            buildFallbackButtons(mount);
        }

        updateForeverActiveState(mount);
        console.log('[Prompt Composer] Generate Forever mirrored under generate button');
        return true;
    }

    function scheduleMount() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            if (mountGenerateForever()) return;
            if (retryCount < 40) {
                retryCount++;
                setTimeout(scheduleMount, 500);
            }
        }, 80);
    }

    window.addEventListener('pc-generate-forever-changed', scheduleStateSync);

    setInterval(function () {
        syncForeverFlagFromInterval();
        var mount = document.getElementById('pc_generate_forever_mount');
        if (mount && mount.dataset.mounted === '1') {
            updateForeverActiveState(mount);
        }
    }, 500);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleMount);
    } else {
        scheduleMount();
    }

    try {
        new MutationObserver(scheduleMount).observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
    } catch (_) { /* ignore */ }
})();
