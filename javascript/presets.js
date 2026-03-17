/**
 * Preset Manager - Save/load/delete prompt presets
 */
(function() {
    'use strict';

    let presets = [];
    let selectedPresetId = null;

    function init() {
        const container = document.getElementById('pc_presets_container');
        if (!container) {
            setTimeout(init, 500);
            return;
        }
        setupEventListeners();
        loadPresets();
        console.log('[Prompt Composer] Preset Manager initialized');
    }

    async function loadPresets() {
        try {
            const resp = await fetch('/prompt-composer/api/presets');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            presets = data.presets || [];
            renderPresetList();
        } catch (err) {
            console.error('[Prompt Composer] Failed to load presets:', err);
        }
    }

    function normalizePresetName(name) {
        let s = (name || '').trim();
        while (s.includes('//')) s = s.replaceAll('//', '/');
        s = s.replace(/^\/+|\/+$/g, '');
        return s;
    }

    function splitCategory(name) {
        const s = normalizePresetName(name);
        const idx = s.indexOf('/');
        if (idx === -1) return { category: '', shortName: s };
        return { category: s.slice(0, idx), shortName: s.slice(idx + 1) };
    }

    function renderPresetList() {
        const container = document.getElementById('pc_presets_container');
        if (!container) return;

        if (presets.length === 0) {
            container.innerHTML = '<div class="pc-empty">保存済みプリセットなし</div>';
            return;
        }

        // Compact preset UI (dropdown with category + buttons) to avoid a long right column
        const groups = {};
        presets.forEach(p => {
            const { category } = splitCategory(p.name || '');
            const key = category || '(未分類)';
            if (!groups[key]) groups[key] = [];
            groups[key].push(p);
        });

        const groupNames = Object.keys(groups);
        groupNames.sort((a, b) => {
            if (a === '(未分類)') return 1;
            if (b === '(未分類)') return -1;
            return a.localeCompare(b, 'ja');
        });

        // keep selection if possible
        if (!selectedPresetId || !presets.some(p => p.id === selectedPresetId)) {
            selectedPresetId = presets[0]?.id || null;
        }

        let optionsHtml = '';
        groupNames.forEach(group => {
            optionsHtml += `<optgroup label="${escapeHtml(group)}">`;
            groups[group].forEach(p => {
                const parts = splitCategory(p.name || '');
                const displayName = parts.shortName || p.name || '';
                const sel = p.id === selectedPresetId ? ' selected' : '';
                optionsHtml += `<option value="${escapeHtml(p.id)}"${sel}>${escapeHtml(displayName)}</option>`;
            });
            optionsHtml += `</optgroup>`;
        });

        const selected = presets.find(p => p.id === selectedPresetId) || presets[0];
        const dateStr = selected?.updatedAt ? new Date(selected.updatedAt).toLocaleDateString('ja-JP') : '';
        const fullName = selected?.name ? escapeHtml(selected.name) : '';

        const html = `
            <div class="pc-preset-compact">
                <div class="pc-preset-compact-row">
                    <select id="pc_preset_select" class="pc-preset-select">
                        ${optionsHtml}
                    </select>
                    <div class="pc-preset-actions">
                        <button class="pc-preset-load" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="読込">📥</button>
                        <button class="pc-preset-overwrite" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="上書き">💾</button>
                        <button class="pc-preset-delete" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="削除">🗑️</button>
                    </div>
                </div>
                <div class="pc-preset-compact-meta">
                    <span class="pc-preset-compact-name">${fullName}</span>
                    ${dateStr ? `<span class="pc-preset-compact-date">${escapeHtml(dateStr)}</span>` : ''}
                </div>
            </div>
        `;

        container.innerHTML = html;

        const select = container.querySelector('#pc_preset_select');
        if (select) {
            select.addEventListener('change', (e) => {
                selectedPresetId = e.target.value;
                renderPresetList(); // refresh meta + button dataset
            });
        }

        const loadBtn = container.querySelector('.pc-preset-load');
        const owBtn = container.querySelector('.pc-preset-overwrite');
        const delBtn = container.querySelector('.pc-preset-delete');
        if (loadBtn) loadBtn.addEventListener('click', (e) => onLoadPreset(e.currentTarget.dataset.presetId));
        if (owBtn) owBtn.addEventListener('click', (e) => onOverwritePreset(e.currentTarget.dataset.presetId));
        if (delBtn) delBtn.addEventListener('click', (e) => onDeletePreset(e.currentTarget.dataset.presetId));
    }

    function setupEventListeners() {
        // Save button
        const saveBtn = document.getElementById('pc_preset_save');
        if (saveBtn) {
            saveBtn.addEventListener('click', onSavePreset);
        }
    }

    async function onSavePreset() {
        const nameEl = document.getElementById('pc_preset_name');
        const input = nameEl ? (nameEl.querySelector('input') || nameEl.querySelector('textarea')) : null;
        const rawName = input ? input.value.trim() : '';
        const name = normalizePresetName(rawName);

        if (!name) {
            alert('プリセット名を入力してください');
            return;
        }

        if (!window.PromptComposer) return;

        const state = window.PromptComposer.getState();
        const existing = presets.find(p => normalizePresetName(p.name) === name);
        if (existing) {
            if (!confirm(`"${name}" は既に存在します。上書きしますか？`)) return;
        }
        const data = {
            id: existing ? existing.id : undefined,
            name: name,
            blocks: state.blocks,
            negativeBlocks: state.negativeBlocks,
            orderProfile: state.orderProfile
        };

        try {
            const resp = await fetch('/prompt-composer/api/presets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            
            if (input) input.value = '';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            
            await loadPresets();
        } catch (err) {
            console.error('[Prompt Composer] Save failed:', err);
            alert('保存に失敗しました');
        }
    }

    async function onLoadPreset(presetId) {
        try {
            const resp = await fetch(`/prompt-composer/api/presets/${presetId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const preset = await resp.json();

            if (window.PromptComposer) {
                window.PromptComposer.loadState(preset);
            }
        } catch (err) {
            console.error('[Prompt Composer] Load failed:', err);
            alert('読込に失敗しました');
        }
    }

    async function onOverwritePreset(presetId) {
        const preset = presets.find(p => p.id === presetId);
        if (!preset) return;

        if (!confirm(`"${preset.name}" を上書きしますか？`)) return;
        if (!window.PromptComposer) return;

        const state = window.PromptComposer.getState();
        const data = {
            id: presetId,
            name: preset.name,
            blocks: state.blocks,
            negativeBlocks: state.negativeBlocks,
            orderProfile: state.orderProfile
        };

        try {
            const resp = await fetch('/prompt-composer/api/presets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            await loadPresets();
        } catch (err) {
            console.error('[Prompt Composer] Overwrite failed:', err);
        }
    }

    async function onDeletePreset(presetId) {
        const preset = presets.find(p => p.id === presetId);
        if (!preset) return;

        if (!confirm(`"${preset.name}" を削除しますか？`)) return;

        try {
            const resp = await fetch(`/prompt-composer/api/presets/${presetId}`, {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            await loadPresets();
        } catch (err) {
            console.error('[Prompt Composer] Delete failed:', err);
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    window.PresetManager = { init, loadPresets, refresh: loadPresets };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 2000));
    } else {
        setTimeout(init, 2000);
    }

    const observer = new MutationObserver((mutations, obs) => {
        if (document.getElementById('pc_presets_container')) {
            obs.disconnect();
            setTimeout(init, 500);
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

})();
