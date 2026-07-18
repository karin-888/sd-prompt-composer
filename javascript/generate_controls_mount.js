/**
 * Mirror txt2img Skip / Interrupt controls under Prompt Composer generate button.
 * Visible only while generation is in progress.
 */
(function () {
    'use strict';

    var retryCount = 0;
    var debounceTimer = null;
    var syncTimer = null;

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document;
    }

    function getControlHost(target, kind) {
        var root = appRoot();
        return root.getElementById(target + '_' + kind)
            || root.querySelector('#' + target + '_' + kind);
    }

    function getControlButton(target, kind) {
        var host = getControlHost(target, kind);
        if (!host) return null;
        if (host.tagName === 'BUTTON') return host;
        return host.querySelector('button') || host;
    }

    function isControlVisible(target, kind) {
        var btn = getControlButton(target, kind);
        return !!(btn && btn.offsetParent);
    }

    function isGenerateForeverActive() {
        try {
            if (window.PromptSync && typeof window.PromptSync.isGenerateForeverActive === 'function') {
                return window.PromptSync.isGenerateForeverActive();
            }
        } catch (_) { /* ignore */ }
        return !!window.generateOnRepeatInterval;
    }

    function hasTxt2imgTaskId() {
        try {
            if (typeof localGet === 'function') {
                return !!localGet('txt2img_task_id', null);
            }
        } catch (_) { /* ignore */ }
        return false;
    }

    function isTxt2imgGenerating() {
        if (isControlVisible('txt2img', 'skip')) return true;
        if (isControlVisible('txt2img', 'interrupt')) return true;
        if (isControlVisible('txt2img', 'interrupting')) return true;
        return hasTxt2imgTaskId();
    }

    function isControlsSessionActive() {
        return isGenerateForeverActive() || isTxt2imgGenerating();
    }

    function triggerSourceControl(target, kind) {
        var btn = getControlButton(target, kind);
        if (!btn) return false;
        btn.click();
        return true;
    }

    function bindMirrorButton(cloneBtn, target, kind) {
        if (!cloneBtn) return;
        cloneBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            triggerSourceControl(target, kind);
        });
    }

    function updateControlsVisibility(mount) {
        if (!mount) return;
        var foreverActive = isGenerateForeverActive();
        var generating = isTxt2imgGenerating();
        var sessionActive = foreverActive || generating;
        mount.hidden = !sessionActive;
        mount.classList.toggle('is-generating', sessionActive);
        mount.classList.toggle('is-forever-session', foreverActive);

        var skipSrc = getControlButton('txt2img', 'skip');
        var interruptSrc = getControlButton('txt2img', 'interrupt');
        var interruptingVisible = isControlVisible('txt2img', 'interrupting');

        var skipBtn = mount.querySelector('.pc-generate-skip-btn');
        var interruptBtn = mount.querySelector('.pc-generate-interrupt-btn');

        if (skipBtn) {
            skipBtn.hidden = !skipSrc;
            // During Generate Forever, keep Skip enabled so the current run can be skipped.
            skipBtn.disabled = !skipSrc || (!generating && !foreverActive);
        }
        if (interruptBtn) {
            interruptBtn.hidden = !interruptSrc || interruptingVisible;
            interruptBtn.disabled = !interruptSrc || interruptingVisible || (!generating && !foreverActive);
        }
    }

    function buildControls(mount) {
        mount.innerHTML =
            '<div class="pc-generate-controls-row">' +
            '<button type="button" class="pc-generate-control-btn pc-generate-skip-btn">⏭ スキップ</button>' +
            '<button type="button" class="pc-generate-control-btn pc-generate-interrupt-btn">⛔ 中断</button>' +
            '</div>';

        bindMirrorButton(
            mount.querySelector('.pc-generate-skip-btn'),
            'txt2img',
            'skip'
        );
        bindMirrorButton(
            mount.querySelector('.pc-generate-interrupt-btn'),
            'txt2img',
            'interrupt'
        );
    }

    function mountGenerateControls() {
        var mount = document.getElementById('pc_generate_controls_mount');
        if (!mount) return false;

        var skipSrc = getControlButton('txt2img', 'skip');
        var interruptSrc = getControlButton('txt2img', 'interrupt');
        if (!skipSrc && !interruptSrc) return false;

        if (mount.dataset.mounted !== '1') {
            buildControls(mount);
            mount.dataset.mounted = '1';
            console.log('[Prompt Composer] Skip / Interrupt mirrored under generate button');
        }

        updateControlsVisibility(mount);
        return true;
    }

    function scheduleMount() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            if (mountGenerateControls()) {
                retryCount = 0;
                return;
            }
            if (retryCount < 40) {
                retryCount++;
                setTimeout(scheduleMount, 500);
            }
        }, 80);
    }

    function startVisibilitySync() {
        if (syncTimer) return;
        syncTimer = setInterval(function () {
            var mount = document.getElementById('pc_generate_controls_mount');
            if (!mount || mount.dataset.mounted !== '1') return;
            if (!isControlsSessionActive()) return;
            updateControlsVisibility(mount);
        }, 500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleMount);
    } else {
        scheduleMount();
    }
    startVisibilitySync();

    window.addEventListener('pc-txt2img-generation-start', function () {
        var mount = document.getElementById('pc_generate_controls_mount');
        if (mount && mount.dataset.mounted === '1') {
            updateControlsVisibility(mount);
        } else {
            scheduleMount();
        }
    });

    window.addEventListener('pc-generate-forever-changed', function () {
        var mount = document.getElementById('pc_generate_controls_mount');
        if (mount && mount.dataset.mounted === '1') {
            updateControlsVisibility(mount);
        } else {
            scheduleMount();
        }
    });

    if (typeof onUiUpdate === 'function') {
        onUiUpdate(function () {
            var mount = document.getElementById('pc_generate_controls_mount');
            if (mount && mount.dataset.mounted === '1') return;
            scheduleMount();
        });
    }
})();
