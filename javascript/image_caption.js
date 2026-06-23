/**
 * Prompt Composer — 参照画像 → 文章（Vision タブ）
 */
(function () {
    'use strict';

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document.getElementById('gradio-app') || document;
    }

    function getTextareaValue(elemId) {
        const root = appRoot();
        const host = root.getElementById(elemId);
        if (!host) return '';
        const ta = host.querySelector('textarea');
        return ta ? (ta.value || '').trim() : '';
    }

    function getCheckboxValue(elemId) {
        const root = appRoot();
        const host = root.getElementById(elemId);
        if (!host) return false;
        const input = host.querySelector('input[type="checkbox"]');
        return input ? !!input.checked : false;
    }

    function getDropdownValue(elemId) {
        const root = appRoot();
        const host = root.getElementById(elemId);
        if (!host) return '';
        const input = host.querySelector('input[type="text"]');
        if (input && (input.value || '').trim()) return input.value.trim();
        const selected = host.querySelector('span.single-select, .selected');
        if (selected && (selected.textContent || '').trim()) {
            return selected.textContent.trim();
        }
        return '';
    }

    function getOutputStyleKey() {
        const label = getDropdownValue('pc_vision_output_style');
        if (label.indexOf('シンプル') >= 0) return 'simple';
        return 'detailed';
    }

    function flashButton(btn, message, ms) {
        if (!btn) return;
        if (!btn.dataset.pcVisionOrigLabel) {
            btn.dataset.pcVisionOrigLabel = (btn.textContent || '').trim();
        }
        const restore = btn.dataset.pcVisionOrigLabel;
        btn.textContent = message;
        setTimeout(function () {
            btn.textContent = restore;
        }, ms || 1400);
    }

    async function splitCaptionText(text) {
        const raw = (text || '').trim();
        if (!raw) return { formatted: '', tags: [] };
        try {
            const style = getOutputStyleKey();
            const url =
                '/prompt-composer/api/vision-split?text=' +
                encodeURIComponent(raw.slice(0, 8000)) +
                '&style=' +
                encodeURIComponent(style);
            const resp = await fetch(url);
            if (!resp.ok) return { formatted: raw, tags: [] };
            return await resp.json();
        } catch (_) {
            return { formatted: raw, tags: [] };
        }
    }

    async function prepareTextForApply(text) {
        if (!getCheckboxValue('pc_vision_auto_split')) {
            return text;
        }
        const data = await splitCaptionText(text);
        return (data.formatted || text).trim();
    }

    async function applyToBlock(blockType) {
        const PC = window.PromptComposer;
        if (!PC || typeof PC.applyTextToBlockType !== 'function') {
            alert('Prompt Composer がまだ読み込まれていません。プロンプト編集タブを一度開いてから再試行してください。');
            return false;
        }
        let text = getTextareaValue('pc_vision_result');
        if (!text) {
            alert('先に画像を解析するか、文章を入力してください。');
            return false;
        }
        text = await prepareTextForApply(text);
        if (!text) return false;
        const replace = getCheckboxValue('pc_vision_apply_replace');
        const ok = PC.applyTextToBlockType(blockType, text, replace ? 'replace' : 'append');
        if (!ok) {
            alert('対象ブロックが見つかりませんでした。');
            return false;
        }
        return true;
    }

    function switchToEditTab() {
        const root = appRoot();
        const tabs = root.getElementById('pc_workspace_tabs');
        if (!tabs) return false;
        const buttons = tabs.querySelectorAll('.tab-nav button, .tab-nav > button, div.tab-nav button');
        for (let i = 0; i < buttons.length; i++) {
            const label = (buttons[i].textContent || '').trim();
            if (label.indexOf('プロンプト編集') >= 0) {
                buttons[i].click();
                return true;
            }
        }
        if (buttons.length) {
            buttons[0].click();
            return true;
        }
        return false;
    }

    function bindButton(elemId, blockType, successLabel) {
        const root = appRoot();
        const host = root.getElementById(elemId);
        if (!host) return;
        const btn = host.tagName === 'BUTTON' ? host : host.querySelector('button');
        if (!btn || btn.dataset.pcVisionBound === '1') return;
        btn.dataset.pcVisionBound = '1';
        btn.addEventListener('click', function () {
            applyToBlock(blockType).then(function (ok) {
                if (ok) {
                    flashButton(btn, successLabel || '✅ 反映しました');
                    switchToEditTab();
                }
            });
        });
    }

    function bindSwitchEdit() {
        const root = appRoot();
        const host = root.getElementById('pc_vision_switch_edit');
        if (!host) return;
        const btn = host.tagName === 'BUTTON' ? host : host.querySelector('button');
        if (!btn || btn.dataset.pcVisionBound === '1') return;
        btn.dataset.pcVisionBound = '1';
        btn.addEventListener('click', function () {
            if (switchToEditTab()) {
                flashButton(btn, '✅ 移動しました');
            }
        });
    }

    function setup() {
        bindButton('pc_vision_apply_outfit', 'outfit', '✅ 衣装へ');
        bindButton('pc_vision_apply_appearance', 'appearance', '✅ 外見へ');
        bindButton('pc_vision_apply_character', 'character', '✅ キャラへ');
        bindButton('pc_vision_apply_background', 'background', '✅ 背景へ');
        bindSwitchEdit();
    }

    const visionButtonIds = [
        'pc_vision_apply_outfit',
        'pc_vision_apply_appearance',
        'pc_vision_apply_character',
        'pc_vision_apply_background',
        'pc_vision_switch_edit'
    ];

    function visionButtonsReady() {
        const root = appRoot();
        return visionButtonIds.every((elemId) => {
            const host = root.getElementById(elemId);
            if (!host) return false;
            const btn = host.tagName === 'BUTTON' ? host : host.querySelector('button');
            return btn && btn.dataset.pcVisionBound === '1';
        });
    }

    let debounce = null;
    let domObserver = null;

    function stopDomObserver() {
        if (!domObserver) return;
        try {
            domObserver.disconnect();
        } catch (_) { /* ignore */ }
        domObserver = null;
    }

    function scheduleSetup() {
        if (debounce) clearTimeout(debounce);
        debounce = setTimeout(function () {
            debounce = null;
            setup();
            if (visionButtonsReady()) stopDomObserver();
        }, 200);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleSetup);
    } else {
        scheduleSetup();
    }

    try {
        domObserver = new MutationObserver(function () {
            if (visionButtonsReady()) return;
            scheduleSetup();
        });
        domObserver.observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
    } catch (_) { /* ignore */ }

    if (typeof onUiUpdate === 'function') {
        onUiUpdate(scheduleSetup);
    }

    window.PromptComposerVision = {
        applyToBlock,
        switchToEditTab,
        splitCaptionText,
        prepareTextForApply,
    };
})();
