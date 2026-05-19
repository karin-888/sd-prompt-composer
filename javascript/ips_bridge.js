/**
 * Bridge: Infinite Prompt Studio (iframe) -> Prompt Composer blocks
 */
(function() {
    'use strict';

    function getPromptComposer() {
        try {
            if (window.PromptComposer && typeof window.PromptComposer.importFromIPS === 'function') {
                return window.PromptComposer;
            }
        } catch (_) {}
        return null;
    }

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) {}
        return document;
    }

    function switchToPromptComposerTab() {
        const root = appRoot();
        const direct =
            root.querySelector('#tab_prompt_composer button') ||
            root.querySelector('button#tab_prompt_composer');
        if (direct) {
            direct.click();
            return true;
        }
        const tabs = root.querySelectorAll('#tabs > .tab-nav button, #tabs button');
        for (const btn of tabs) {
            const label = (btn.textContent || '').trim();
            if (/prompt composer/i.test(label)) {
                btn.click();
                return true;
            }
        }
        return false;
    }

    async function importFromIPS(payload) {
        const PC = getPromptComposer();
        if (!PC) {
            return { ok: false, error: 'Prompt Composer が読み込まれていません。WebUI を再読み込みしてください。' };
        }
        const result = PC.importFromIPS(payload);
        if (result.ok && payload && payload.options && payload.options.switchTab) {
            switchToPromptComposerTab();
        }
        return result;
    }

    async function fetchPresets() {
        const resp = await fetch('/prompt-composer/api/presets');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        return data.presets || [];
    }

    async function fetchPreset(presetId) {
        if (!presetId) return null;
        const resp = await fetch(`/prompt-composer/api/presets/${encodeURIComponent(presetId)}`);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return await resp.json();
    }

    async function loadPresetToComposer(presetId) {
        const preset = await fetchPreset(presetId);
        const PC = getPromptComposer();
        if (!PC || !preset) {
            return { ok: false, error: 'プリセットを読み込めませんでした' };
        }
        PC.loadState(preset);
        return { ok: true, preset };
    }

    window.IpsPromptBridge = {
        importFromIPS,
        switchToPromptComposerTab,
        fetchPresets,
        fetchPreset,
        loadPresetToComposer,
        isAvailable() {
            return !!getPromptComposer();
        }
    };

    window.addEventListener('message', async (event) => {
        const data = event.data;
        if (!data || data.type !== 'ips-pc-import') return;
        const result = await importFromIPS(data.payload || {});
        if (event.source && typeof event.source.postMessage === 'function') {
            event.source.postMessage({
                type: 'ips-pc-import-result',
                requestId: data.requestId,
                ok: !!result.ok,
                error: result.error || null,
                imported: result.imported
            }, '*');
        }
    });

    console.log('[Prompt Composer] IPS bridge loaded');
})();
