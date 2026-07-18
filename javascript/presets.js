/**
 * Preset Manager - Save/load/delete prompt presets
 */
(function() {
    'use strict';

    let presets = [];
    let selectedPresetId = null;
    const collapsedPresetFolders = new Set();

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

    function formatSaveDate(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return '';
            return d.toLocaleDateString('ja-JP', { year: 'numeric', month: 'numeric', day: 'numeric' });
        } catch (_) {
            return '';
        }
    }

    function renderPresetList() {
        const container = document.getElementById('pc_presets_container');
        if (!container) return;

        if (presets.length === 0) {
            container.innerHTML = '<div class="pc-empty">保存済みプリセットなし</div>';
            return;
        }

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
        groupNames.forEach(g => {
            groups[g].sort((a, b) => {
                const an = splitCategory(a.name || '').shortName || a.name || '';
                const bn = splitCategory(b.name || '').shortName || b.name || '';
                return an.localeCompare(bn, 'ja');
            });
        });

        if (!selectedPresetId || !presets.some(p => p.id === selectedPresetId)) {
            selectedPresetId = presets[0]?.id || null;
        }

        const selected = presets.find(p => p.id === selectedPresetId) || presets[0];
        const selectedShort = selected
            ? (splitCategory(selected.name || '').shortName || selected.name || '')
            : '';
        const dateStr = formatSaveDate(selected?.updatedAt);
        const memoBadge = selected?.hasMemo
            ? '<span class="pc-preset-memo-badge" title="Markdownメモ付き">MD</span>'
            : '';

        let treeHtml = '';
        groupNames.forEach(group => {
            const open = !collapsedPresetFolders.has(group);
            const items = groups[group];
            treeHtml += `
                <div class="pc-file-tree-folder${open ? ' is-open' : ''}" data-folder="${escapeHtml(group)}">
                    <button type="button" class="pc-file-tree-folder-head" data-folder="${escapeHtml(group)}" title="${escapeHtml(group)}">
                        <span class="pc-file-tree-caret">${open ? '▾' : '▸'}</span>
                        <span class="pc-file-tree-folder-name">${escapeHtml(group)}</span>
                        <span class="pc-file-tree-count">${items.length}</span>
                    </button>
                    <div class="pc-file-tree-children"${open ? '' : ' hidden'}>
            `;
            items.forEach((p, idx) => {
                const parts = splitCategory(p.name || '');
                const shortName = parts.shortName || p.name || '';
                const isSel = p.id === selectedPresetId;
                const itemDate = formatSaveDate(p.updatedAt);
                const itemMemo = p.hasMemo ? '<span class="pc-preset-memo-badge" title="Markdownメモ付き">MD</span>' : '';
                const branch = idx === items.length - 1 ? '└──' : '├──';
                treeHtml += `
                    <button type="button"
                        class="pc-file-tree-item${isSel ? ' is-selected' : ''}"
                        data-preset-id="${escapeHtml(p.id)}"
                        title="${escapeHtml(p.name || '')}">
                        <span class="pc-file-tree-branch" aria-hidden="true">${branch}</span>
                        <span class="pc-file-tree-item-main">
                            <span class="pc-file-tree-col-name">${escapeHtml(shortName)}</span>
                            ${itemMemo}
                        </span>
                        ${itemDate ? `<span class="pc-file-tree-item-date">${escapeHtml(itemDate)}</span>` : ''}
                    </button>
                `;
            });
            treeHtml += `</div></div>`;
        });

        container.innerHTML = `
            <div class="pc-preset-tree-wrap">
                <div class="pc-file-tree-meta">
                    <span class="pc-preset-compact-name" title="${escapeHtml(selected?.name || selectedShort)}">${escapeHtml(selectedShort)}</span>
                    ${dateStr ? `<span class="pc-preset-compact-date">${escapeHtml(dateStr)}</span>` : ''}
                    ${memoBadge}
                    <div class="pc-file-tree-actions">
                        <button type="button" class="pc-preset-load" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="読込">読込</button>
                        <button type="button" class="pc-preset-overwrite" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="上書き">上書き</button>
                        <button type="button" class="pc-preset-delete" data-preset-id="${escapeHtml(selectedPresetId || '')}" title="削除">削除</button>
                    </div>
                </div>
                <div class="pc-file-tree" role="tree" aria-label="プリセット一覧">
                    ${treeHtml}
                </div>
            </div>
        `;

        container.querySelectorAll('.pc-file-tree-folder-head').forEach(btn => {
            btn.addEventListener('click', () => {
                const folder = btn.dataset.folder || '';
                if (collapsedPresetFolders.has(folder)) collapsedPresetFolders.delete(folder);
                else collapsedPresetFolders.add(folder);
                renderPresetList();
            });
        });

        container.querySelectorAll('.pc-file-tree-item').forEach(btn => {
            btn.addEventListener('click', () => {
                selectedPresetId = btn.dataset.presetId || null;
                renderPresetList();
            });
            btn.addEventListener('dblclick', () => {
                selectedPresetId = btn.dataset.presetId || null;
                if (selectedPresetId) onLoadPreset(selectedPresetId);
            });
        });

        const loadBtn = container.querySelector('.pc-preset-load');
        const owBtn = container.querySelector('.pc-preset-overwrite');
        const delBtn = container.querySelector('.pc-preset-delete');
        if (loadBtn) loadBtn.addEventListener('click', () => onLoadPreset(loadBtn.dataset.presetId));
        if (owBtn) owBtn.addEventListener('click', () => onOverwritePreset(owBtn.dataset.presetId));
        if (delBtn) delBtn.addEventListener('click', () => onDeletePreset(delBtn.dataset.presetId));

        requestAnimationFrame(() => {
            layoutPresetTreeScroll();
            setTimeout(layoutPresetTreeScroll, 100);
            setTimeout(layoutPresetTreeScroll, 300);
        });
    }

    function layoutPresetTreeScroll() {
        const tree = document.querySelector('#pc_presets_container .pc-file-tree');
        if (!tree) return;

        // Prefer remaining viewport below the tree top so Gradio flex quirks can't block scroll.
        const top = tree.getBoundingClientRect().top;
        const bottomPad = 28;
        const available = Math.floor(window.innerHeight - top - bottomPad);
        const maxH = Math.max(180, available);
        tree.style.maxHeight = maxH + 'px';
        tree.style.height = maxH + 'px';
        tree.style.overflowY = 'auto';
        tree.style.overflowX = 'hidden';
        tree.style.minHeight = '0';

        if (tree.dataset.pcScrollBound !== '1') {
            tree.dataset.pcScrollBound = '1';
            tree.addEventListener('wheel', (e) => {
                e.stopPropagation();
            }, { passive: true });
        }
    }

    function setupPresetLayoutWatchers() {
        if (window._pcPresetScrollWatch) return;
        window._pcPresetScrollWatch = true;
        window.addEventListener('resize', () => layoutPresetTreeScroll());
        // Left tab switches / layout settles
        document.addEventListener('click', (e) => {
            if (e.target.closest('#pc_left_tabs .tab-nav')) {
                setTimeout(layoutPresetTreeScroll, 50);
                setTimeout(layoutPresetTreeScroll, 200);
            }
        });
    }

    function setupEventListeners() {
        setupPresetLayoutWatchers();
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
            orderProfile: state.orderProfile,
            memo: state.characterMemo || '',
            memoFormat: state.characterMemo ? (state.memoFormat || 'markdown') : ''
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
            orderProfile: state.orderProfile,
            memo: state.characterMemo || '',
            memoFormat: state.characterMemo ? (state.memoFormat || 'markdown') : ''
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
    function startPresetObserver() {
        const target = (typeof document.body !== 'undefined' && document.body)
            ? document.body
            : document.documentElement;
        if (!(target instanceof Node)) {
            requestAnimationFrame(startPresetObserver);
            return;
        }
        try {
            observer.observe(target, { childList: true, subtree: true });
        } catch (_) {
            requestAnimationFrame(startPresetObserver);
        }
    }
    startPresetObserver();

})();
