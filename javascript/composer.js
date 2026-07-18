/**
 * Prompt Composer - Block-based prompt editor
 * Handles block creation, token management, drag-and-drop reordering,
 * and final prompt generation.
 */
(function() {
    'use strict';

    // ===== Auto-save (localStorage) =====
    const AUTOSAVE_KEY = 'pc_autosave_v1';
    let autosaveTimer = null;
    let isRestoring = false;

    // ===== Block Definitions =====
    const DEFAULT_BLOCKS = [
        { type: 'quality',     label: '🏆 品質',      order: 0 },
        { type: 'subject',     label: '🎯 主題',      order: 1 },
        { type: 'character',   label: '👤 キャラ',    order: 2 },
        { type: 'appearance',  label: '✨ 外見',      order: 3 },
        { type: 'outfit',      label: '👗 衣装',      order: 4 },
        { type: 'expression',  label: '😊 表情',      order: 5 },
        { type: 'composition', label: '📐 構図',      order: 6 },
        { type: 'background',  label: '🌄 背景',      order: 7 },
        { type: 'lighting',    label: '💡 光',        order: 8 },
        { type: 'style',       label: '🎨 画風',      order: 9 },
        { type: 'lora',        label: '🔧 LoRA',     order: 10 },
        { type: 'embedding',   label: '📦 Embedding', order: 11 },
    ];

    const NEGATIVE_BLOCKS = [
        { type: 'negative', label: '🚫 Negative', order: 0 },
    ];

    // ===== State =====
    let characterMemo = '';
    let blocks = [];
    let negativeBlocks = [];
    let currentOrderProfile = 'illustrious_standard';
    let draggedBlock = null;
    let draggedToken = null; // { tokenIds: string[], fromBlockId: string }
    let selectedTokenIds = new Set(); // multi-select support
    let blockDragScrollListenerBound = false;
    const jpLookupTried = new Map(); // token.id -> normalized key
    let jpBackfillTimer = null;
    let batchUpdateDepth = 0;
    let renderBlocksRaf = 0;
    let pcContainerDelegated = false;
    // NOTE: token selection is used for keyboard weight adjust (↑↓).

    function beginBatchUpdate() {
        batchUpdateDepth++;
    }

    function endBatchUpdate() {
        batchUpdateDepth = Math.max(0, batchUpdateDepth - 1);
        if (batchUpdateDepth === 0) {
            scheduleRenderBlocks();
        }
    }

    function scheduleRenderBlocks() {
        if (batchUpdateDepth > 0) return;
        if (renderBlocksRaf) return;
        renderBlocksRaf = requestAnimationFrame(() => {
            renderBlocksRaf = 0;
            renderBlocksImmediate();
        });
    }

    function renderBlocks() {
        scheduleRenderBlocks();
    }

    function getCharacterMemoEl() {
        return document.getElementById('pc_character_memo');
    }

    function getCharacterMemo() {
        const el = getCharacterMemoEl();
        return el ? String(el.value || '') : characterMemo;
    }

    function setCharacterMemo(value, options = {}) {
        characterMemo = String(value || '');
        const el = getCharacterMemoEl();
        if (el && el.value !== characterMemo) {
            el.value = characterMemo;
        }
        if (characterMemoMode === 'preview') {
            updateCharacterMemoPreview();
        }
        if (!options.silent && !isRestoring) {
            scheduleAutoSave();
        }
    }

    function getCharacterMemoPreviewEl() {
        return document.getElementById('pc_character_memo_preview');
    }

    let characterMemoMode = 'edit';

    function updateCharacterMemoPreview() {
        const preview = getCharacterMemoPreviewEl();
        if (!preview) return;
        const render = window.PcMarkdown && typeof window.PcMarkdown.render === 'function'
            ? window.PcMarkdown.render
            : (text) => `<pre class="pc-md-fallback">${(text || '').replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}</pre>`;
        preview.innerHTML = render(getCharacterMemo());
    }

    function setCharacterMemoMode(mode) {
        const next = mode === 'preview' ? 'preview' : 'edit';
        characterMemoMode = next;
        const textarea = getCharacterMemoEl();
        const preview = getCharacterMemoPreviewEl();
        const wrap = document.querySelector('.pc-character-memo-wrap');
        if (wrap) {
            wrap.querySelectorAll('.pc-memo-tab').forEach((btn) => {
                const active = btn.dataset.mode === next;
                btn.classList.toggle('is-active', active);
                btn.setAttribute('aria-selected', active ? 'true' : 'false');
            });
        }
        if (textarea) textarea.hidden = next === 'preview';
        if (preview) {
            preview.hidden = next !== 'preview';
            if (next === 'preview') updateCharacterMemoPreview();
        }
    }

    function setupCharacterMemoTabs() {
        const wrap = document.querySelector('.pc-character-memo-wrap');
        if (!wrap || wrap.dataset.pcMemoTabsBound === '1') return;
        wrap.dataset.pcMemoTabsBound = '1';
        wrap.querySelectorAll('.pc-memo-tab').forEach((btn) => {
            btn.addEventListener('click', (event) => {
                event.preventDefault();
                setCharacterMemoMode(btn.dataset.mode || 'edit');
            });
        });
        setCharacterMemoMode(characterMemoMode);
    }

    function setupCharacterMemoListener() {
        const el = getCharacterMemoEl();
        if (!el || el.dataset.pcMemoBound === '1') return;
        el.dataset.pcMemoBound = '1';
        el.addEventListener('input', () => {
            characterMemo = String(el.value || '');
            if (characterMemoMode === 'preview') {
                updateCharacterMemoPreview();
            }
            scheduleAutoSave();
        });
        setupCharacterMemoTabs();
    }

    // ===== Initialization =====
    function init() {
        // Wait for DOM
        const container = document.getElementById('pc_blocks_container');
        if (!container) {
            setTimeout(init, 500);
            return;
        }
        // DOMContentLoaded + onUiLoaded both schedule init; avoid duplicate listeners / reset.
        if (container.dataset.pcComposerInit === '1') {
            setupCharacterMemoListener();
            setupCharacterMemoTabs();
            setCharacterMemo(characterMemo, { silent: true });
            return;
        }

        // Initialize default blocks
        blocks = DEFAULT_BLOCKS.map(def => ({
            id: generateId(),
            type: def.type,
            label: def.label,
            order: def.order,
            enabled: true,
            tokens: []
        }));

        negativeBlocks = NEGATIVE_BLOCKS.map(def => ({
            id: generateId(),
            type: def.type,
            label: def.label,
            order: def.order,
            enabled: true,
            tokens: []
        }));

        // Restore autosaved state if available
        if (!tryRestoreAutoSave()) {
            renderBlocks();
        }
        setupEventListeners();
        setupCharacterMemoListener();
        setCharacterMemo(characterMemo, { silent: true });

        container.dataset.pcComposerInit = '1';
        console.log('[Prompt Composer] Composer initialized');
    }

    function scheduleAutoSave() {
        if (isRestoring) return;
        clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
            try {
                if (!window.PromptComposer) return;
                const state = window.PromptComposer.getState();
                const payload = {
                    v: 1,
                    savedAt: Date.now(),
                    state
                };
                localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(payload));
            } catch (e) {
                // ignore storage errors (quota/private mode)
            }
        }, 600);
    }

    function tryRestoreAutoSave() {
        let raw = null;
        try {
            raw = localStorage.getItem(AUTOSAVE_KEY);
        } catch (e) {
            raw = null;
        }
        if (!raw) return false;
        try {
            const payload = JSON.parse(raw);
            const st = payload && payload.state;
            if (!st || !st.blocks || !Array.isArray(st.blocks)) return false;
            // Guard: ignore broken autosave that would erase the UI (empty blocks)
            if (st.blocks.length === 0) {
                try { localStorage.removeItem(AUTOSAVE_KEY); } catch (_) {}
                return false;
            }
            isRestoring = true;
            loadState(st);
            isRestoring = false;
            return true;
        } catch (e) {
            return false;
        } finally {
            isRestoring = false;
        }
    }

    // ===== Rendering =====
    let tagsetRefreshTimer = null;

    function scheduleTagsetBarRefresh() {
        clearTimeout(tagsetRefreshTimer);
        tagsetRefreshTimer = setTimeout(() => {
            tagsetRefreshTimer = null;
            const tagsets = window.PromptComposerBlockTagsets;
            if (!tagsets) return;
            if (typeof tagsets.refreshBarsFromCache === 'function') {
                tagsets.refreshBarsFromCache();
            } else if (typeof tagsets.refreshAllBlockTagSetBars === 'function') {
                tagsets.refreshAllBlockTagSetBars().catch(() => {});
            }
        }, 150);
    }

    function renderBlocksImmediate() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;

        let html = '';
        
        // Positive blocks
        html += '<div class="pc-blocks-section"><div class="pc-blocks-section-label">Positive Prompt</div>';
        blocks.forEach((block, idx) => {
            html += renderBlock(block, idx, false);
        });
        html += '</div>';
        
        // Negative blocks
        html += '<div class="pc-blocks-section pc-blocks-negative"><div class="pc-blocks-section-label">Negative Prompt</div>';
        negativeBlocks.forEach((block, idx) => {
            html += renderBlock(block, idx, true);
        });
        html += '</div>';

        container.innerHTML = html;

        // Re-attach event listeners
        attachBlockListeners();
        updateFinalPrompt();

        scheduleTagsetBarRefresh();

        dispatchStateChange('render');

        scheduleAutoSave();
    }

    function renderBlock(block, index, isNegative) {
        const enabledClass = block.enabled ? 'pc-block-enabled' : 'pc-block-disabled';
        const toggleIcon = block.enabled ? '✅' : '⬜';
        const prefix = isNegative ? 'neg' : 'pos';
        
        let tokensHtml = '';
        block.tokens.forEach((token, tidx) => {
            const hasWeight = (typeof token.weight === 'number' && !Number.isNaN(token.weight) && token.weight !== 1);
            const weightStr = hasWeight ? `:${token.weight}` : '';
            const sourceClass = token.sourceType ? `pc-token-${token.sourceType}` : '';
            const hiddenClass = token.hidden === true ? 'pc-token-hidden' : '';
            const rawText = String(token.text || token.label || '').trim().toUpperCase();
            const rawOriginal = String(token.text || token.label || '').trim();
            const isWildcardToken = token.sourceType === 'wildcard'
                || /^__[A-Za-z0-9][\w./\-]*__$/.test(rawOriginal)
                || /^__[^_].*__$/.test(rawOriginal);
            const specialClass = rawText === 'BREAK' ? 'pc-token-break'
                : (rawText === 'AND' ? 'pc-token-and'
                    : (isWildcardToken ? 'pc-token-wildcard' : ''));
            const isLoRA = token.sourceType === 'lora';
            const isEmbedding = token.sourceType === 'embedding';
            const isTW = token.isTrigger === true;

            let badgeClass = '';
            let badgeText = '';
            if (isTW) {
                badgeClass = 'pc-token-source-tw';
                badgeText = 'TW';
            } else if (isLoRA) {
                badgeClass = 'pc-token-source-lora';
                badgeText = 'LoRA';
            } else if (isEmbedding) {
                badgeClass = 'pc-token-source-embedding';
                badgeText = 'Emb';
            } else if (isWildcardToken) {
                badgeClass = 'pc-token-source-wildcard';
                badgeText = 'WC';
            }

            const sourceBadge = badgeText
                ? `<span class="pc-token-source-badge ${badgeClass}">${badgeText}</span>`
                : '';

            const titleParts = [];
            if (isTW) titleParts.push('[TW]');
            if (isLoRA) titleParts.push('[LoRA]');
            if (isEmbedding) titleParts.push('[Embedding]');
            if (isWildcardToken) titleParts.push('[Wildcard]');
            if (token.hidden === true) titleParts.push('[HIDDEN]');
            titleParts.push(token.text);
            const title = escapeHtml(titleParts.join(' '));

            const previewAttr = token.previewUrl ? ` data-preview-url="${token.previewUrl}"` : '';
            // Color rule:
            // - negative weight (<0): blue
            // - non-1.0 weight (including 0.1..0.9 and >1): red
            const weightClass = hasWeight
                ? (token.weight < 0 ? 'pc-token-weight-minus' : 'pc-token-weight-plus')
                : '';

            tokensHtml += `
                <span class="pc-token ${sourceClass} ${hiddenClass} ${specialClass}" draggable="true" data-token-id="${token.id}" data-block-id="${block.id}" data-token-idx="${tidx}" title="${title}"${previewAttr}>
                    ${sourceBadge}
                    <span class="pc-token-label">
                        <span class="pc-token-label-text">${escapeHtml(token.label)}</span>
                        ${hasWeight ? `<span class="pc-token-weight ${weightClass}">${escapeHtml(weightStr)}</span>` : ''}
                        ${token.jp ? `<span class="pc-token-jp">${escapeHtml(token.jp)}</span>` : ''}
                    </span>
                    <button type="button" class="pc-token-edit" data-block-id="${block.id}" data-token-idx="${tidx}" title="編集（Enter で確定 / Esc で取消）">✎</button>
                    <button type="button" class="pc-token-remove" data-block-id="${block.id}" data-token-idx="${tidx}">×</button>
                </span>
            `;
        });

        return `
            <div class="pc-block ${enabledClass}" 
                 data-block-id="${block.id}" 
                 data-block-type="${block.type}"
                 data-is-negative="${isNegative}"
                 draggable="false">
                <div class="pc-block-header pc-block-header-draggable" draggable="true" title="このヘッダーをドラッグして欄の順番を入れ替え">
                    <span class="pc-block-drag-handle">⠿</span>
                    <button class="pc-block-toggle" data-block-id="${block.id}">${toggleIcon}</button>
                    <span class="pc-block-label">${block.label}</span>
                    <button class="pc-block-clear" data-block-id="${block.id}" title="この欄のタグをすべて削除" aria-label="枠内タグクリア">枠内タグクリア</button>
                    <button class="pc-block-delete" data-block-id="${block.id}" title="この欄を削除" aria-label="枠ごと削除">枠ごと削除</button>
                    <span class="pc-block-count">タグ数：${block.tokens.length}</span>
                </div>
                <div class="pc-block-tagset-bar" data-block-id="${block.id}" data-block-type="${block.type}">
                    <input type="text" class="pc-block-tagset-name" data-block-id="${block.id}" placeholder="保存名..." autocomplete="off" />
                    <div class="pc-block-tagset-pick" data-block-id="${block.id}">
                        <button type="button" class="pc-block-tagset-pick-btn" data-block-id="${block.id}" aria-haspopup="listbox" aria-expanded="false">
                            <span class="pc-block-tagset-pick-label">保存済み</span>
                        </button>
                        <div class="pc-block-tagset-pick-menu" data-block-id="${block.id}" role="listbox"></div>
                    </div>
                    <div class="pc-block-tagset-actions">
                        <button type="button" class="pc-block-tagset-btn pc-block-tagset-save-new" data-block-id="${block.id}" title="新規保存" aria-label="新規保存">新規</button>
                        <button type="button" class="pc-block-tagset-btn pc-block-tagset-load" data-block-id="${block.id}" title="読込（Shift+クリックで追加）" aria-label="読込">読込</button>
                        <button type="button" class="pc-block-tagset-btn pc-block-tagset-overwrite" data-block-id="${block.id}" title="上書き" aria-label="上書き">上書き</button>
                        <button type="button" class="pc-block-tagset-btn pc-block-tagset-delete" data-block-id="${block.id}" title="削除" aria-label="削除">削除</button>
                    </div>
                </div>
                <div class="pc-block-body">
                    <div class="pc-token-list">${tokensHtml}</div>
                    <div class="pc-token-input-row">
                        <input type="text" 
                               class="pc-token-input" 
                               data-block-id="${block.id}"
                               placeholder="タグ入力... (Enter で追加)"
                               autocomplete="off">
                    </div>
                </div>
            </div>
        `;
    }

    // ===== Warnings and Auto-format =====
    async function checkWarnings() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;

        // 1. Check duplicate tokens
        const allTokens = {};
        let hasDuplicates = false;
        
        blocks.forEach(block => {
            if (!block.enabled) return;
            block.tokens.forEach(token => {
                if (token.hidden === true) return;
                const text = token.text.toLowerCase().trim();
                if (!allTokens[text]) {
                    allTokens[text] = [block.id];
                } else {
                    allTokens[text].push(block.id);
                    hasDuplicates = true;
                }
            });
        });

        // Clear previous duplicate highlights
        container.querySelectorAll('.pc-token-duplicate').forEach(el => el.classList.remove('pc-token-duplicate'));
        
        // Highlight new duplicates
        if (hasDuplicates) {
            Object.entries(allTokens).forEach(([text, blockIds]) => {
                if (blockIds.length > 1) {
                    blocks.forEach(block => {
                        block.tokens.forEach((token, tidx) => {
                            if (token.text.toLowerCase().trim() === text) {
                                const tokenEl = container.querySelector(`.pc-token[data-block-id="${block.id}"][data-token-idx="${tidx}"]`);
                                if (tokenEl) tokenEl.classList.add('pc-token-duplicate');
                            }
                        });
                    });
                }
            });
        }

        // 2. Check Order
        let hasOrderWarning = false;
        try {
            const profileId = currentOrderProfile;
            if (profileId) {
                const resp = await fetch(`/prompt-composer/api/order-profiles/${profileId}`);
                if (resp.ok) {
                    const profile = await resp.json();
                    const expectedOrder = profile.order || [];
                    
                    // Filter current blocks to only those in the profile, and extract their types
                    const currentTypes = blocks.map(b => b.type).filter(t => expectedOrder.includes(t));
                    const expectedFiltered = expectedOrder.filter(t => currentTypes.includes(t));
                    
                    // Check if currentTypes matches expectedFiltered
                    for (let i = 0; i < currentTypes.length; i++) {
                        if (currentTypes[i] !== expectedFiltered[i]) {
                            hasOrderWarning = true;
                            break;
                        }
                    }
                }
            }
        } catch (e) {
            console.warn('[Prompt Composer] Order check failed', e);
        }

        // Update UI for order warning
        const warningBanner = document.getElementById('pc_order_warning');
        if (warningBanner) {
            if (hasOrderWarning) {
                warningBanner.style.display = 'block';
                warningBanner.innerHTML = '⚠️ <b>注意:</b> ブロックの順序が現在のプロファイル推奨と異なります。<button id="pc_warning_sort_btn">推奨順に並び替え</button>';
                const btn = document.getElementById('pc_warning_sort_btn');
                if (btn) btn.addEventListener('click', sortBlocksByProfile);
            } else {
                warningBanner.style.display = 'none';
            }
        }
    }

    // ===== Event Listeners =====
    function setupEventListeners() {
        // 欄ドラッグ中、ブラウザ既定の自動スクロールは上方向が弱いことがあるため
        // #pc_composer_area を明示的にスクロールする（下方向だけ効く問題の対策）。
        if (!blockDragScrollListenerBound) {
            blockDragScrollListenerBound = true;
            document.addEventListener('dragover', onDocumentDragOverBlockDragAutoScroll, { passive: true });
        }

        // Block reorder modal
        const sortBtn = document.getElementById('pc_sort_blocks');
        if (sortBtn) {
            sortBtn.addEventListener('click', showBlockReorderModal);
        }

        // Clear blocks button
        const clearBtn = document.getElementById('pc_clear_blocks');
        if (clearBtn) {
            clearBtn.addEventListener('click', clearAllTokens);
        }

        // Add block button
        const addBtn = document.getElementById('pc_add_block');
        if (addBtn) {
            addBtn.addEventListener('click', showAddBlockDialog);
        }

        // Order profile: custom UI is built in ensureOrderProfileManagerUI (mount #pc_order_profile).

        // Enhance order profile UI: dynamic options + save/delete
        setTimeout(() => {
            try { ensureOrderProfileManagerUI(); } catch (_) { /* ignore */ }
        }, 50);

        // Auto format
        const autoFormatBtn = document.getElementById('pc_auto_format');
        if (autoFormatBtn) {
            autoFormatBtn.addEventListener('click', autoFormatBlocks);
        }

        // Templates
        const templateSelect = document.getElementById('pc_template_select');
        if (templateSelect) {
            const selectEl = templateSelect.querySelector('select') || templateSelect.querySelector('input');
            if (selectEl) {
                selectEl.addEventListener('change', (e) => {
                    if (e.target.value !== '選択しない') {
                        applyTemplate(e.target.value);
                        e.target.value = '選択しない';
                        // For Gradio dropdown we need to trigger change
                        e.target.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                });
            }
        }

        // Keyboard weight adjust for selected tokens (↑↓)
        // When a token is selected (clicked), ArrowUp/ArrowDown will adjust its weight.
        // This is global so it works even when the token list has focus.
        if (!window.__PromptComposerWeightKeysBound) {
            window.__PromptComposerWeightKeysBound = true;
            document.addEventListener('keydown', (e) => {
                // Don't interfere while typing in input fields or using the tag suggest popup.
                const active = document.activeElement;
                if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
                if (tagSuggestBox && tagSuggestBox.style.display === 'block') return;
                if (!selectedTokenIds || selectedTokenIds.size === 0) return;

                if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
                e.preventDefault();

                const delta = (e.shiftKey ? 0.1 : 0.05) * (e.key === 'ArrowUp' ? 1 : -1);
                adjustSelectedTokenWeights(delta);
            });
        }
    }

    function getCurrentBlockTypeOrder() {
        // positive blocks display order only
        return (blocks || []).map(b => b.type).filter(Boolean);
    }

    async function fetchOrderProfiles() {
        const resp = await fetch('/prompt-composer/api/order-profiles');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        return (data && data.profiles) ? data.profiles : {};
    }

    function ensureOrderProfileManagerUI() {
        const root = document.getElementById('pc_order_profile');
        if (!root) return;
        // Rebuild if an older dropdown-based manager is still present
        const existingMgr = root.querySelector('.pc-order-profile-manager');
        if (existingMgr) {
            if (existingMgr.querySelector('.pc-order-profile-tree')) return;
            existingMgr.remove();
        }

        // Hide Gradio's original dropdown UI to avoid duplicated controls.
        // Capture any pre-existing Gradio <select> NOW — after we inject our UI,
        // root.querySelector('select') could resolve to OUR select and syncing it
        // would dispatch change on ourselves → infinite recursion (stack overflow).
        const mirrorGradioSelect = root.querySelector('select');

        const legacySelect = mirrorGradioSelect;
        if (legacySelect) {
            const legacyWrap = legacySelect.closest('.wrap') || legacySelect.parentElement;
            if (legacyWrap && legacyWrap.style) legacyWrap.style.display = 'none';
            legacySelect.style.display = 'none';
        }
        const legacyInput = root.querySelector('input');
        if (legacyInput) {
            const legacyWrap = legacyInput.closest('.wrap') || legacyInput.parentElement;
            if (legacyWrap && legacyWrap.style) legacyWrap.style.display = 'none';
            legacyInput.style.display = 'none';
        }

        const wrap = document.createElement('div');
        wrap.className = 'pc-order-profile-manager';
        wrap.innerHTML = `
            <div class="pc-order-profile-row">
                <input type="text" class="pc-order-profile-name" placeholder="順序プロファイル名...（項目/保存名）">
                <button type="button" class="pc-order-profile-save" title="新規保存">保存</button>
                <button type="button" class="pc-order-profile-overwrite" title="上書き保存">上書き</button>
                <button type="button" class="pc-order-profile-delete" title="削除">削除</button>
            </div>
            <div class="pc-file-tree-meta">
                <span class="pc-order-profile-selected-name"></span>
                <span class="pc-order-profile-selected-date"></span>
                <div class="pc-file-tree-actions">
                    <button type="button" class="pc-order-profile-load" title="選択した順序を読込">読込</button>
                </div>
            </div>
            <div class="pc-file-tree pc-order-profile-tree" role="tree" aria-label="順序プロファイル一覧"></div>
            <div class="pc-order-profile-hint">ダブルクリックまたは「読込」で適用（表示順のみ対象）</div>
        `;
        root.appendChild(wrap);

        const nameInput = wrap.querySelector('.pc-order-profile-name');
        const loadBtn = wrap.querySelector('.pc-order-profile-load');
        const saveBtn = wrap.querySelector('.pc-order-profile-save');
        const overwriteBtn = wrap.querySelector('.pc-order-profile-overwrite');
        const delBtn = wrap.querySelector('.pc-order-profile-delete');
        const treeEl = wrap.querySelector('.pc-order-profile-tree');
        const selectedNameEl = wrap.querySelector('.pc-order-profile-selected-name');
        const selectedDateEl = wrap.querySelector('.pc-order-profile-selected-date');
        const collapsedFolders = new Set();
        let selectedProfileId = currentOrderProfile || 'illustrious_standard';

        const isBuiltinProfile = (id) => {
            return id === 'illustrious_standard' || id === 'character_focus' || id === 'background_focus';
        };

        const setCurrentProfile = (id) => {
            if (!id) return;
            currentOrderProfile = id;
            selectedProfileId = id;
            // Mirror only Gradio's original <select>; never dispatch on our tree.
            const gradioSel = mirrorGradioSelect;
            if (gradioSel && Array.from(gradioSel.options).some(o => o.value === id)) {
                if (gradioSel.value !== id) gradioSel.value = id;
                gradioSel.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };

        const getSelectedProfileId = () => {
            return selectedProfileId || currentOrderProfile;
        };

        const profileLabel = (profiles, id) => {
            const p = profiles[id] || {};
            return p.name || id;
        };

        const splitProfileCategory = (name) => {
            let s = (name || '').trim();
            while (s.includes('//')) s = s.replaceAll('//', '/');
            s = s.replace(/^\/+|\/+$/g, '');
            const idx = s.indexOf('/');
            if (idx === -1) return { category: '', shortName: s };
            return { category: s.slice(0, idx), shortName: s.slice(idx + 1) };
        };

        const escapeHtmlLocal = (str) => {
            if (!str) return '';
            const d = document.createElement('div');
            d.textContent = str;
            return d.innerHTML;
        };

        const formatSaveDate = (iso) => {
            if (!iso) return '';
            try {
                const d = new Date(iso);
                if (Number.isNaN(d.getTime())) return '';
                return d.toLocaleDateString('ja-JP', { year: 'numeric', month: 'numeric', day: 'numeric' });
            } catch (_) {
                return '';
            }
        };

        const buildProfileGroups = (profiles) => {
            const groups = {};
            const builtins = ['illustrious_standard', 'character_focus', 'background_focus'];

            builtins.forEach(id => {
                if (!profiles[id]) return;
                const key = '標準';
                if (!groups[key]) groups[key] = [];
                groups[key].push({
                    id,
                    name: profileLabel(profiles, id),
                    builtin: true,
                    updatedAt: profiles[id].updatedAt || ''
                });
            });

            Object.keys(profiles).forEach(id => {
                if (builtins.includes(id)) return;
                const fullName = profileLabel(profiles, id);
                const parts = splitProfileCategory(fullName);
                const key = parts.category || 'ユーザー';
                if (!groups[key]) groups[key] = [];
                groups[key].push({
                    id,
                    name: fullName,
                    shortName: parts.shortName || fullName,
                    builtin: false,
                    updatedAt: profiles[id].updatedAt || ''
                });
            });

            Object.keys(groups).forEach(g => {
                groups[g].sort((a, b) => {
                    const an = a.shortName || a.name || '';
                    const bn = b.shortName || b.name || '';
                    return an.localeCompare(bn, 'ja');
                });
            });
            return groups;
        };

        const renderProfileTree = (profiles) => {
            if (!treeEl) return;
            const groups = buildProfileGroups(profiles || {});
            const groupNames = Object.keys(groups);
            groupNames.sort((a, b) => {
                if (a === '標準') return -1;
                if (b === '標準') return 1;
                if (a === 'ユーザー') return 1;
                if (b === 'ユーザー') return -1;
                return a.localeCompare(b, 'ja');
            });

            if (!selectedProfileId || !Object.keys(profiles).includes(selectedProfileId)) {
                selectedProfileId = groupNames.length ? (groups[groupNames[0]][0]?.id || '') : '';
            }

            let html = '';
            groupNames.forEach(group => {
                const open = !collapsedFolders.has(group);
                const items = groups[group];
                html += `
                    <div class="pc-file-tree-folder${open ? ' is-open' : ''}" data-folder="${escapeHtmlLocal(group)}">
                        <button type="button" class="pc-file-tree-folder-head" data-folder="${escapeHtmlLocal(group)}">
                            <span class="pc-file-tree-caret">${open ? '▾' : '▸'}</span>
                            <span class="pc-file-tree-folder-name">${escapeHtmlLocal(group)}</span>
                            <span class="pc-file-tree-count">${items.length}</span>
                        </button>
                        <div class="pc-file-tree-children"${open ? '' : ' hidden'}>
                `;
                items.forEach((item, idx) => {
                    const shortName = item.shortName || item.name || item.id;
                    const isSel = item.id === selectedProfileId;
                    const itemDate = formatSaveDate(item.updatedAt);
                    const branch = idx === items.length - 1 ? '└──' : '├──';
                    html += `
                        <button type="button"
                            class="pc-file-tree-item${isSel ? ' is-selected' : ''}${item.builtin ? ' is-builtin' : ''}"
                            data-profile-id="${escapeHtmlLocal(item.id)}"
                            title="${escapeHtmlLocal(item.name || item.id)}">
                            <span class="pc-file-tree-branch" aria-hidden="true">${branch}</span>
                            <span class="pc-file-tree-item-main">
                                <span class="pc-file-tree-col-name">${escapeHtmlLocal(shortName)}</span>
                            </span>
                            ${itemDate ? `<span class="pc-file-tree-item-date">${escapeHtmlLocal(itemDate)}</span>` : ''}
                        </button>
                    `;
                });
                html += `</div></div>`;
            });
            treeEl.innerHTML = html || '<div class="pc-empty">プロファイルなし</div>';

            if (selectedNameEl) {
                const sel = profiles[selectedProfileId];
                const label = selectedProfileId ? profileLabel(profiles, selectedProfileId) : '';
                const short = label ? (splitProfileCategory(label).shortName || label) : '';
                selectedNameEl.textContent = short || '';
                if (selectedDateEl) {
                    selectedDateEl.textContent = formatSaveDate(sel?.updatedAt) || '';
                }
            }

            treeEl.querySelectorAll('.pc-file-tree-folder-head').forEach(btn => {
                btn.addEventListener('click', () => {
                    const folder = btn.dataset.folder || '';
                    if (collapsedFolders.has(folder)) collapsedFolders.delete(folder);
                    else collapsedFolders.add(folder);
                    renderProfileTree(profiles);
                });
            });

            treeEl.querySelectorAll('.pc-file-tree-item').forEach(btn => {
                btn.addEventListener('click', () => {
                    selectedProfileId = btn.dataset.profileId || '';
                    setCurrentProfile(selectedProfileId);
                    try { checkWarnings(); } catch (_) { /* ignore */ }
                    renderProfileTree(profiles);
                    if (nameInput && selectedProfileId && !isBuiltinProfile(selectedProfileId)) {
                        nameInput.value = profileLabel(profiles, selectedProfileId);
                    }
                });
                btn.addEventListener('dblclick', async () => {
                    selectedProfileId = btn.dataset.profileId || '';
                    if (!selectedProfileId) return;
                    setCurrentProfile(selectedProfileId);
                    await sortBlocksByProfile(selectedProfileId);
                    if (nameInput) nameInput.value = profileLabel(profiles, selectedProfileId);
                });
            });
        };

        const refreshSelect = async () => {
            const profiles = await fetchOrderProfiles();
            renderProfileTree(profiles);
            if (selectedProfileId) setCurrentProfile(selectedProfileId);
        };

        // initial fill
        refreshSelect().catch(() => {});

        if (loadBtn) {
            loadBtn.addEventListener('click', async () => {
                const id = getSelectedProfileId();
                if (!id) {
                    alert('読込対象の順序プロファイルを選択してください');
                    return;
                }
                setCurrentProfile(id);
                await sortBlocksByProfile(id);
                try {
                    const profiles = await fetchOrderProfiles();
                    if (nameInput) nameInput.value = profileLabel(profiles, id);
                } catch (_) { /* ignore */ }
            });
        }

        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                const name = (nameInput && nameInput.value || '').trim();
                if (!name) {
                    alert('順序プロファイル名を入力してください');
                    return;
                }
                const order = getCurrentBlockTypeOrder();
                if (!Array.isArray(order) || order.length === 0) {
                    alert('保存対象のブロック順が空です。Positive側のブロックを1つ以上残してください。');
                    return;
                }

                try {
                    const profiles = await fetchOrderProfiles();
                    const existingId = Object.keys(profiles).find(id => (profiles[id]?.name || '').trim() === name);
                    if (existingId && !isBuiltinProfile(existingId)) {
                        alert(`同名のプロファイルが存在します: ${name}\n上書きしたい場合は「上書き」を使ってください。`);
                        return;
                    }
                } catch (_) { /* ignore */ }

                try {
                    const payload = { name, order };
                    const resp = await fetch('/prompt-composer/api/order-profiles', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    let data = null;
                    try { data = await resp.json(); } catch (_) { data = null; }
                    if (!resp.ok) {
                        const reason = (data && data.error) ? `\n理由: ${data.error}` : '';
                        alert(`保存に失敗しました${reason}`);
                        return;
                    }
                    const savedId = data && data.id;
                    if (savedId) selectedProfileId = savedId;
                    await refreshSelect();
                    if (savedId) setCurrentProfile(savedId);
                    if (nameInput) nameInput.value = '';
                    alert('順序プロファイルを保存しました。');
                } catch (e) {
                    alert(`保存に失敗しました\n通信エラー: ${e && e.message ? e.message : e}`);
                }
            });
        }

        if (overwriteBtn) {
            overwriteBtn.addEventListener('click', async () => {
                const id = getSelectedProfileId();
                if (!id) {
                    alert('上書き対象の順序プロファイルを選択してください');
                    return;
                }
                if (isBuiltinProfile(id)) {
                    alert('標準プロファイルは上書きできません。新規保存してください。');
                    return;
                }
                const name = (nameInput && nameInput.value || '').trim();
                const order = getCurrentBlockTypeOrder();
                if (!Array.isArray(order) || order.length === 0) {
                    alert('保存対象のブロック順が空です。Positive側のブロックを1つ以上残してください。');
                    return;
                }
                try {
                    const profiles = await fetchOrderProfiles();
                    const fallbackName = profileLabel(profiles, id);
                    const payload = { id, name: name || fallbackName, order };
                    const resp = await fetch('/prompt-composer/api/order-profiles', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    let data = null;
                    try { data = await resp.json(); } catch (_) { data = null; }
                    if (!resp.ok) {
                        const reason = (data && data.error) ? `\n理由: ${data.error}` : '';
                        alert(`上書き保存に失敗しました${reason}`);
                        return;
                    }
                    selectedProfileId = id;
                    await refreshSelect();
                    setCurrentProfile(id);
                    alert('順序プロファイルを上書き保存しました。');
                } catch (e) {
                    alert(`上書き保存に失敗しました\n通信エラー: ${e && e.message ? e.message : e}`);
                }
            });
        }

        if (delBtn) {
            delBtn.addEventListener('click', async () => {
                const id = getSelectedProfileId();
                if (!id) return;
                if (isBuiltinProfile(id)) {
                    alert('標準プロファイルは削除できません');
                    return;
                }
                if (!confirm('この順序プロファイルを削除しますか？')) return;
                const resp = await fetch(`/prompt-composer/api/order-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
                if (!resp.ok) {
                    alert('削除に失敗しました');
                    return;
                }
                selectedProfileId = '';
                await refreshSelect();
                const nextId = getSelectedProfileId();
                if (nextId) setCurrentProfile(nextId);
            });
        }
    }

    function _clamp(n, min, max) {
        return Math.max(min, Math.min(max, n));
    }

    function _roundWeight(w) {
        // keep stable + readable values
        return Math.round(w * 100) / 100;
    }

    function _parseLoraTag(text) {
        const raw = (text || '').trim();
        // Typical: <lora:name:0.8>
        // name can contain underscores and other chars; we take the last ":<num>>" as weight
        const m = raw.match(/^<lora:(.+):(-?[0-9.]+)>$/i);
        if (!m) return null;
        const name = (m[1] || '').trim();
        const w = parseFloat(m[2]);
        if (!name || !Number.isFinite(w)) return null;
        return { name, weight: w };
    }

    function _getTokenBaseText(token) {
        const raw = (token && token.text) ? String(token.text) : '';
        const lora = _parseLoraTag(raw);
        if (lora) return `<lora:${lora.name}>`;
        const m = raw.match(/^\((.+):(-?[0-9.]+)\)$/);
        if (m) return m[1];
        return raw;
    }

    function adjustSelectedTokenWeights(delta) {
        const ids = new Set(selectedTokenIds);
        const allBlocks = [...blocks, ...negativeBlocks];
        let changed = 0;

        allBlocks.forEach(b => {
            b.tokens.forEach(t => {
                if (!ids.has(t.id)) return;
                const rawText = String(t.text || '');
                const loraParsed = _parseLoraTag(rawText);

                const current = (typeof t.weight === 'number' && !Number.isNaN(t.weight))
                    ? t.weight
                    : (() => {
                        // For LoRA, read weight from <lora:...:w>
                        if (loraParsed) return loraParsed.weight;
                        // Otherwise, try to read (tag:w)
                        const m = rawText.match(/^\(.+?:(-?[0-9.]+)\)$/);
                        if (m) {
                            const parsed = parseFloat(m[1]);
                            return Number.isFinite(parsed) ? parsed : 1.0;
                        }
                        return 1.0;
                    })();

                const next = _roundWeight(_clamp(current + delta, -10.0, 10.0));
                t.weight = next;
                // Ensure final prompt reflects the weight by updating token.text.
                // Keep token.label as-is for display; token.text is the emitted prompt part.
                if (loraParsed || t.sourceType === 'lora' || rawText.trim().toLowerCase().startsWith('<lora:')) {
                    // LoRA: never wrap with parentheses; update inside the <lora:...:w> tag
                    const name = loraParsed ? loraParsed.name : (() => {
                        // best-effort extraction from text even if malformed
                        const mm = rawText.match(/^<lora:(.+?)(?::(-?[0-9.]+))?>$/i);
                        return mm ? (mm[1] || '').trim() : rawText.replace(/^<lora:/i, '').replace(/>$/,'').trim();
                    })();
                    t.text = `<lora:${name}:${next}>`;
                } else {
                    const base = _getTokenBaseText(t);
                    if (next === 1.0) {
                        t.weight = null;
                        t.text = base;
                    } else {
                        t.text = `(${base}:${next})`;
                    }
                }
                changed++;
            });
        });

        if (changed > 0) {
            renderBlocks();
        }
    }

    function ensurePcDelegatedListeners(container) {
        if (pcContainerDelegated) return;
        pcContainerDelegated = true;

        container.addEventListener('mousedown', (e) => {
            if (e.target.closest('.pc-block-toggle, .pc-block-clear, .pc-block-delete, .pc-block-tagset-btn, .pc-block-tagset-pick-btn, .pc-block-tagset-pick-item, .pc-token-edit, .pc-token-remove')) {
                e.stopPropagation();
            }
        });

        container.addEventListener('click', async (e) => {
            const TAG = window.PromptComposerBlockTagsets;

            const pickBtn = e.target.closest('.pc-block-tagset-pick-btn');
            if (pickBtn) {
                e.preventDefault();
                e.stopPropagation();
                const blockId = pickBtn.dataset.blockId;
                if (blockId && TAG && typeof TAG.togglePickMenu === 'function') {
                    TAG.togglePickMenu(blockId);
                }
                return;
            }

            const saveNewBtn = e.target.closest('.pc-block-tagset-save-new');
            if (saveNewBtn) {
                e.preventDefault();
                e.stopPropagation();
                const blockId = saveNewBtn.dataset.blockId;
                if (blockId && TAG) {
                    try { await TAG.saveNew(blockId); } catch (err) {
                        console.warn('[Prompt Composer] Save new failed:', err);
                        alert('保存に失敗しました');
                    }
                }
                return;
            }

            const loadBtn = e.target.closest('.pc-block-tagset-load');
            if (loadBtn) {
                e.preventDefault();
                e.stopPropagation();
                const blockId = loadBtn.dataset.blockId;
                if (blockId && TAG) {
                    try { await TAG.load(blockId, e.shiftKey); } catch (err) {
                        console.warn('[Prompt Composer] Load failed:', err);
                        alert('読込に失敗しました');
                    }
                }
                return;
            }

            const overwriteBtn = e.target.closest('.pc-block-tagset-overwrite');
            if (overwriteBtn) {
                e.preventDefault();
                e.stopPropagation();
                const blockId = overwriteBtn.dataset.blockId;
                if (blockId && TAG) {
                    try { await TAG.overwrite(blockId); } catch (err) {
                        console.warn('[Prompt Composer] Overwrite failed:', err);
                        alert('上書きに失敗しました');
                    }
                }
                return;
            }

            const delTagsetBtn = e.target.closest('.pc-block-tagset-delete');
            if (delTagsetBtn) {
                e.preventDefault();
                e.stopPropagation();
                const blockId = delTagsetBtn.dataset.blockId;
                if (blockId && TAG) {
                    try { await TAG.delete(blockId); } catch (err) {
                        console.warn('[Prompt Composer] Delete failed:', err);
                        alert('削除に失敗しました');
                    }
                }
                return;
            }

            const editBtn = e.target.closest('.pc-token-edit');
            if (editBtn) {
                e.stopPropagation();
                e.preventDefault();
                const blockId = editBtn.dataset.blockId;
                const tokenIdx = parseInt(editBtn.dataset.tokenIdx, 10);
                if (blockId && !Number.isNaN(tokenIdx)) startTokenInlineEdit(blockId, tokenIdx);
                return;
            }

            const removeBtn = e.target.closest('.pc-token-remove');
            if (removeBtn) {
                e.stopPropagation();
                const blockId = removeBtn.dataset.blockId;
                const tokenIdx = parseInt(removeBtn.dataset.tokenIdx, 10);
                if (blockId && !Number.isNaN(tokenIdx)) removeToken(blockId, tokenIdx);
                return;
            }

            const clearBtn = e.target.closest('.pc-block-clear');
            if (clearBtn) {
                e.stopPropagation();
                const blockId = clearBtn.dataset.blockId;
                if (blockId) clearBlockTokens(blockId);
                return;
            }

            const deleteBlockBtn = e.target.closest('.pc-block-delete');
            if (deleteBlockBtn) {
                e.stopPropagation();
                const blockId = deleteBlockBtn.dataset.blockId;
                if (blockId) deleteBlock(blockId);
                return;
            }

            const toggleBtn = e.target.closest('.pc-block-toggle');
            if (toggleBtn) {
                const blockId = toggleBtn.dataset.blockId;
                if (blockId) toggleBlock(blockId);
                return;
            }

            const tokenEl = e.target.closest('.pc-token');
            if (tokenEl && !tokenEl.classList.contains('pc-token-editing') && !e.target.closest('.pc-token-edit-input')) {
                const id = tokenEl.dataset.tokenId;
                if (!id) return;
                const isMulti = e.ctrlKey || e.metaKey;
                if (!isMulti) {
                    clearTokenSelection();
                    selectedTokenIds.add(id);
                } else if (selectedTokenIds.has(id)) {
                    selectedTokenIds.delete(id);
                } else {
                    selectedTokenIds.add(id);
                }
                applyTokenSelectionClasses();
            }
        });

        container.addEventListener('dblclick', (e) => {
            const label = e.target.closest('.pc-block-label');
            if (label) {
                e.preventDefault();
                e.stopPropagation();
                const blockEl = label.closest('.pc-block');
                const blockId = blockEl ? blockEl.dataset.blockId : null;
                if (blockId) renameBlockLabel(blockId);
                return;
            }

            const tokenEl = e.target.closest('.pc-token');
            if (!tokenEl || tokenEl.classList.contains('pc-token-editing')) return;
            if (e.target.closest('.pc-token-edit-input, .pc-token-remove, .pc-token-edit')) return;
            e.preventDefault();
            e.stopPropagation();
            const blockId = tokenEl.dataset.blockId;
            const tokenIdx = parseInt(tokenEl.dataset.tokenIdx, 10);
            if (blockId && !Number.isNaN(tokenIdx)) toggleTokenHidden(blockId, tokenIdx);
        });

        container.addEventListener('dragstart', (e) => {
            if (e.target.closest('.pc-token[draggable="true"]')) {
                onTokenDragStart(e);
                return;
            }
            if (e.target.closest('.pc-block-header-draggable')) {
                onDragStart(e);
            }
        });

        container.addEventListener('dragover', (e) => {
            if (e.target.closest('.pc-token, .pc-token-list')) {
                onTokenDragOver(e);
            } else if (e.target.closest('.pc-block')) {
                onDragOver(e);
            }
        });

        container.addEventListener('drop', (e) => {
            if (e.target.closest('.pc-token, .pc-token-list')) {
                onTokenDrop(e);
            } else if (e.target.closest('.pc-block')) {
                onDrop(e);
            }
        });

        container.addEventListener('dragend', (e) => {
            if (e.target.closest('.pc-token[draggable="true"]')) {
                onTokenDragEnd(e);
            } else if (e.target.closest('.pc-block-header-draggable')) {
                onDragEnd(e);
            }
        });

        container.addEventListener('input', (e) => {
            const TAG = window.PromptComposerBlockTagsets;
            const inp = e.target.closest('.pc-block-tagset-name');
            if (inp && TAG && inp.dataset.blockId) {
                TAG.onNameInput(inp.dataset.blockId);
            }
        });
    }

    function attachBlockListeners() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;

        ensurePcDelegatedListeners(container);

        container.querySelectorAll('.pc-token-input').forEach(input => {
            if (input.dataset.pcInputBound === '1') return;
            input.dataset.pcInputBound = '1';

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && tagSuggestBox && tagSuggestBox.style.display === 'block' && tagSuggestSelectedIndex >= 0) {
                    return;
                }
                if (e.key === 'Enter' && e.target.value.trim()) {
                    e.preventDefault();
                    const blockId = e.target.dataset.blockId;
                    addTokenFromInput(blockId, e.target.value.trim());
                    e.target.value = '';
                }
            });
            input.addEventListener('focus', (e) => {
                const blockId = e.target.dataset.blockId;
                if (blockId) {
                    window.PromptComposerActiveBlockId = blockId;
                    dispatchActiveBlockChange(blockId);
                }
            });

            try {
                if (typeof window.addAutocompleteToArea === 'function') {
                    window.addAutocompleteToArea(input);
                } else if (typeof addAutocompleteToArea === 'function') {
                    addAutocompleteToArea(input);
                }
            } catch (err) {
                // ignore if tagcomplete is not loaded
            }

            setupLocalTagSuggest(input);
        });
    }

    function onTokenDragStart(e) {
        const tokenEl = e.target.closest('.pc-token');
        if (!tokenEl) return;
        if (tokenEl.classList.contains('pc-token-editing')) return;
        // ブロック全体のドラッグ開始に伝播させない
        e.stopPropagation();
        // ignore drags started from edit / remove button
        if (e.target && e.target.classList && e.target.classList.contains('pc-token-remove')) return;
        if (e.target && e.target.classList && e.target.classList.contains('pc-token-edit')) return;

        const tokenId = tokenEl.dataset.tokenId;
        const blockId = tokenEl.dataset.blockId;
        if (!tokenId || !blockId) return;

        // decide which tokens are moving:
        // Ctrl/⌘ を押しながらドラッグ開始したときだけ「選択中の複数」を対象にする
        const allowMultiDrag = (e.ctrlKey || e.metaKey);
        let movingIds = [];
        if (allowMultiDrag && selectedTokenIds.size > 0 && selectedTokenIds.has(tokenId)) {
            const allBlocks = [...blocks, ...negativeBlocks];
            const sourceBlock = allBlocks.find(b => b.id === blockId);
            if (sourceBlock) {
                const allowed = new Set(sourceBlock.tokens.map(t => t.id));
                movingIds = Array.from(selectedTokenIds).filter(id => allowed.has(id));
            }
        }
        if (!movingIds.length) {
            movingIds = [tokenId];
            clearTokenSelection();
            selectedTokenIds.add(tokenId);
            applyTokenSelectionClasses();
        }

        draggedToken = {
            tokenIds: movingIds,
            fromBlockId: blockId
        };

        tokenEl.classList.add('pc-token-dragging');
        try {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', movingIds.join(','));
        } catch (_) {
            // ignore
        }
    }

    function onTokenDragOver(e) {
        const tokenEl = e.target.closest('.pc-token');
        const listEl = e.target.closest('.pc-token-list');
        if ((!tokenEl && !listEl) || !draggedToken) return;
        // ブロックのドラッグ処理に渡さない
        e.stopPropagation();
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const fromId = draggedToken.fromBlockId;
        const fromNeg = isNegativeBlockId(fromId);

        if (tokenEl) {
            const toId = tokenEl.dataset.blockId;
            if (!toId || isNegativeBlockId(toId) !== fromNeg) return;
            tokenEl.classList.add('pc-token-drop-target');
        } else if (listEl) {
            const blockEl = listEl.closest('.pc-block');
            if (!blockEl) return;
            const toId = blockEl.dataset.blockId;
            if (!toId || isNegativeBlockId(toId) !== fromNeg) return;
            listEl.classList.add('pc-token-drop-target');
        }
    }

    function onTokenDrop(e) {
        const tokenEl = e.target.closest('.pc-token');
        const listEl = e.target.closest('.pc-token-list');
        if (!draggedToken || (!tokenEl && !listEl)) return;
        e.stopPropagation();
        e.preventDefault();

        let blockId = null;
        let rawInsert = 0;

        if (tokenEl) {
            blockId = tokenEl.dataset.blockId;
            rawInsert = parseInt(tokenEl.dataset.tokenIdx, 10);
            if (Number.isNaN(rawInsert)) rawInsert = 0;
        } else if (listEl) {
            const blockEl = listEl.closest('.pc-block');
            if (!blockEl) return;
            blockId = blockEl.dataset.blockId;
            rawInsert = listEl.children.length;
        }

        if (!blockId) return;

        const fromNeg = isNegativeBlockId(draggedToken.fromBlockId);
        const toNeg = isNegativeBlockId(blockId);
        if (fromNeg !== toNeg) return;

        const tokenIds = draggedToken.tokenIds || [];
        if (!tokenIds.length) return;
        const allBlocks = [...blocks, ...negativeBlocks];

        const sourceBlock = allBlocks.find(b => b.id === draggedToken.fromBlockId);
        const targetBlock = allBlocks.find(b => b.id === blockId);
        if (!sourceBlock || !targetBlock) return;

        const movingIndices = [];
        sourceBlock.tokens.forEach((t, i) => {
            if (tokenIds.includes(t.id)) movingIndices.push(i);
        });

        const movedTokens = [];
        const remaining = [];
        sourceBlock.tokens.forEach(t => {
            if (tokenIds.includes(t.id)) {
                movedTokens.push(t);
            } else {
                remaining.push(t);
            }
        });
        sourceBlock.tokens = remaining;

        let insertIdx = rawInsert;
        if (sourceBlock === targetBlock) {
            movingIndices.forEach(i => {
                if (i < insertIdx) insertIdx--;
            });
        }
        insertIdx = Math.max(0, Math.min(insertIdx, targetBlock.tokens.length));
        targetBlock.tokens.splice(insertIdx, 0, ...movedTokens);

        renderBlocks();
    }

    function onTokenDragEnd(e) {
        e.stopPropagation();
        const container = document.getElementById('pc_blocks_container');
        if (container) {
            container.querySelectorAll('.pc-token-dragging').forEach(el => el.classList.remove('pc-token-dragging'));
            container.querySelectorAll('.pc-token-drop-target').forEach(el => el.classList.remove('pc-token-drop-target'));
        }
        draggedToken = null;
    }

    function clearTokenSelection() {
        selectedTokenIds.clear();
        applyTokenSelectionClasses();
    }

    // ===== Local Tag Suggest (danbooru.csv based) =====
    let tagSuggestBox = null;
    let tagSuggestHideTimer = null;
    let tagSuggestActiveInput = null;
    let tagSuggestActiveBlockId = null;
    let tagSuggestSelectedIndex = -1;

    function ensureTagSuggestBox() {
        if (tagSuggestBox) return tagSuggestBox;
        tagSuggestBox = document.createElement('div');
        tagSuggestBox.id = 'pc_tag_suggest';
        tagSuggestBox.className = 'pc-tag-suggest';
        tagSuggestBox.style.display = 'none';
        document.body.appendChild(tagSuggestBox);
        return tagSuggestBox;
    }

    function setupLocalTagSuggest(input) {
        let debounceTimer = null;
        const blockId = input.dataset.blockId;
        if (!blockId) return;

        input.addEventListener('keydown', (e) => {
            if (!tagSuggestBox || tagSuggestBox.style.display === 'none') return;
            const items = Array.from(tagSuggestBox.querySelectorAll('.pc-tag-suggest-item'));
            if (!items.length) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                tagSuggestSelectedIndex = (tagSuggestSelectedIndex + 1) % items.length;
                updateTagSuggestSelection(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                tagSuggestSelectedIndex = (tagSuggestSelectedIndex - 1 + items.length) % items.length;
                updateTagSuggestSelection(items);
            } else if (e.key === 'Enter') {
                if (tagSuggestSelectedIndex >= 0 && tagSuggestSelectedIndex < items.length) {
                    e.preventDefault();
                    const li = items[tagSuggestSelectedIndex];
                    const tag = li.dataset.tag;
                    if (tag) {
                        const jp = (li.dataset.jp || '').trim();
                        addToken(blockId, tag, tag, { sourceType: 'manual', isTrigger: false, jp: jp || null });
                        input.value = '';
                        hideTagSuggest();
                    }
                }
            } else if (e.key === 'Escape') {
                hideTagSuggest();
            }
        });

        input.addEventListener('input', (e) => {
            const value = e.target.value || '';
            clearTimeout(debounceTimer);
            if (!value.trim()) {
                hideTagSuggest();
                return;
            }
            debounceTimer = setTimeout(() => {
                requestTagSuggest(value, input, blockId);
            }, 200);
        });

        input.addEventListener('focus', () => {
            if (input.value && input.value.trim()) {
                requestTagSuggest(input.value, input, blockId);
            }
        });

        input.addEventListener('blur', () => {
            tagSuggestHideTimer = setTimeout(hideTagSuggest, 150);
        });
    }

    async function requestTagSuggest(query, anchorInput, blockId) {
        const box = ensureTagSuggestBox();
        try {
            const params = new URLSearchParams({ q: query, limit: '30' });
            const resp = await fetch('/prompt-composer/api/tag-suggest?' + params.toString());
            if (!resp.ok) {
                hideTagSuggest();
                return;
            }
            const data = await resp.json();
            const items = (data && Array.isArray(data.items)) ? data.items : [];
            if (!items.length) {
                hideTagSuggest();
                return;
            }

            // Position box under the input
            const rect = anchorInput.getBoundingClientRect();
            box.style.left = `${rect.left + window.scrollX}px`;
            box.style.top = `${rect.bottom + window.scrollY + 4}px`;

            tagSuggestActiveInput = anchorInput;
            tagSuggestActiveBlockId = blockId;
            tagSuggestSelectedIndex = -1;

            let html = '<ul class="pc-tag-suggest-list">';
            items.forEach(item => {
                const tag = item.tag || '';
                if (!tag) return;
                const jp = item.jp || '';
                html += `<li class="pc-tag-suggest-item" data-tag="${escapeHtml(tag)}" data-jp="${escapeHtml(jp)}">` +
                    `<span class="pc-tag-suggest-tag">${escapeHtml(tag)}</span>` +
                    (jp ? `<span class="pc-tag-suggest-jp">${escapeHtml(jp)}</span>` : '') +
                    `</li>`;
            });
            html += '</ul>';
            box.innerHTML = html;
            box.style.display = 'block';

            const liNodes = box.querySelectorAll('.pc-tag-suggest-item');
            liNodes.forEach((li, idx) => {
                li.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    const tag = li.dataset.tag;
                    if (!tag) return;
                    const jp = (li.dataset.jp || '').trim();
                    addToken(blockId, tag, tag, { sourceType: 'manual', isTrigger: false, jp: jp || null });
                    anchorInput.value = '';
                    hideTagSuggest();
                });
                li.addEventListener('mouseenter', () => {
                    tagSuggestSelectedIndex = idx;
                    updateTagSuggestSelection(Array.from(liNodes));
                });
            });

            // Cancel pending hide while interacting
            box.addEventListener('mouseenter', () => {
                if (tagSuggestHideTimer) {
                    clearTimeout(tagSuggestHideTimer);
                    tagSuggestHideTimer = null;
                }
            });
            box.addEventListener('mouseleave', () => {
                tagSuggestHideTimer = setTimeout(hideTagSuggest, 120);
            });
        } catch (e) {
            hideTagSuggest();
        }
    }

    function hideTagSuggest() {
        if (tagSuggestBox) {
            tagSuggestBox.style.display = 'none';
            tagSuggestBox.innerHTML = '';
        }
        tagSuggestActiveInput = null;
        tagSuggestActiveBlockId = null;
        tagSuggestSelectedIndex = -1;
    }

    function updateTagSuggestSelection(items) {
        items.forEach((el, i) => {
            if (i === tagSuggestSelectedIndex) {
                el.classList.add('pc-tag-suggest-item-selected');
                el.scrollIntoView({ block: 'nearest' });
            } else {
                el.classList.remove('pc-tag-suggest-item-selected');
            }
        });
    }

    function applyTokenSelectionClasses() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;
        container.querySelectorAll('.pc-token').forEach(el => {
            const id = el.dataset.tokenId;
            if (id && selectedTokenIds.has(id)) {
                el.classList.add('pc-token-selected');
            } else {
                el.classList.remove('pc-token-selected');
            }
        });
    }

    // Token moving UI ("選択タグを移動") removed per request.

    // ===== Block Operations =====
    function toggleBlock(blockId) {
        const block = findBlock(blockId);
        if (block) {
            block.enabled = !block.enabled;
            renderBlocks();
        }
    }

    function pushTokenToBlock(block, label, text, options = {}) {
        const token = {
            id: generateId(),
            label: label,
            text: text || label,
            weight: options.weight || null,
            sourceType: options.sourceType || 'manual',
            isTrigger: options.isTrigger === true,
            hidden: options.hidden === true,
            previewUrl: options.previewUrl || null,
            jp: options.jp || null
        };
        block.tokens.push(token);
        return token;
    }

    function addToken(blockId, label, text, options = {}) {
        const block = findBlock(blockId);
        if (!block) return;
        const token = pushTokenToBlock(block, label, text, options);
        renderBlocks();
        if (!token.jp) {
            const key = getTokenJpLookupKey(token);
            if (key) scheduleJpBackfill(120);
        }
    }

    function addTokensBulk(blockId, tokenSpecs, options = {}) {
        const block = findBlock(blockId);
        if (!block || !tokenSpecs || !tokenSpecs.length) return;
        beginBatchUpdate();
        try {
            tokenSpecs.forEach(spec => {
                if (!spec) return;
                pushTokenToBlock(block, spec.label, spec.text, spec);
            });
        } finally {
            endBatchUpdate();
        }
        if (options.scheduleJpBackfill !== false) {
            scheduleJpBackfill(options.jpBackfillDelay || 200);
        }
    }

    function normComposerSpaces(s) {
        const raw = (s || '').trim();
        if (!raw) return '';
        // Comma-separated fragments: normalize spaces within each tag only, not at separators.
        if (/[,\u3001]/.test(raw)) {
            return raw
                .split(/[,\u3001]/)
                .map(part => part.trim().replace(/^_+/, '').replace(/\s+/g, '_'))
                .filter(part => part.length > 0)
                .join(', ');
        }
        return raw.replace(/\s+/g, '_');
    }

    /**
     * Single prompt fragment typed by the user: plain tag, (tag:w), or <lora:...>.
     */
    function parseComposerTokenSlice(rawText) {
        const rawTrim = (rawText || '').trim();
        if (!rawTrim) return null;

        const loraParsed = _parseLoraTag(rawTrim);
        if (loraParsed) {
            const emittedText = `<lora:${loraParsed.name}:${loraParsed.weight}>`;
            const w = loraParsed.weight;
            const weight = (typeof w === 'number' && Number.isFinite(w) && w !== 1 && !Number.isNaN(w)) ? w : null;
            return { emittedText, label: loraParsed.name.trim(), weight, loraParsed };
        }

        let innerText = rawTrim;
        let weight = null;
        let emittedText = rawTrim;

        const weightMatch = rawTrim.match(/^\((.+):(-?[0-9.]+)\)$/);
        if (weightMatch) {
            innerText = normComposerSpaces(weightMatch[1]);
            weight = parseFloat(weightMatch[2]);
            emittedText = `(${innerText}:${weightMatch[2]})`;
        } else {
            innerText = normComposerSpaces(innerText);
            emittedText = innerText;
        }

        return { emittedText, label: innerText, weight, loraParsed: null };
    }

    function extractTranslatableBase(text) {
        const raw = String(text || '').trim();
        if (!raw) return '';
        if (raw === 'BREAK' || raw === 'AND') return '';
        if (raw.startsWith('__') && raw.endsWith('__')) return '';
        if (_parseLoraTag(raw)) return '';

        // (tag:1.2), (tag:-1.0) -> tag
        const weighted = raw.match(/^\((.+):(-?[0-9.]+)\)$/);
        const base = weighted ? String(weighted[1] || '').trim() : raw;
        if (!base) return '';
        return normComposerSpaces(base);
    }

    function getTokenJpLookupKey(token) {
        if (!token) return '';
        return extractTranslatableBase(token.text || token.label || '');
    }

    function buildTranslationCandidates(base) {
        const norm = String(base || '').trim();
        if (!norm) return [];
        const out = [];
        const push = (v) => {
            const t = String(v || '').trim();
            if (!t) return;
            if (!out.includes(t)) out.push(t);
        };
        push(norm);
        push(norm.toLowerCase());
        if (norm.includes(' ')) push(norm.replace(/\s+/g, '_'));
        if (norm.includes('_')) push(norm.replace(/_+/g, ' '));
        return out;
    }

    async function fetchComposerTagJp(innerLabel, parsed, rawText = null) {
        const base = extractTranslatableBase(innerLabel || rawText || '');
        if (!base) return null;
        // Parsed non-LoRA tags should always use normalized label first.
        const preferred = (parsed && !parsed.loraParsed && innerLabel)
            ? extractTranslatableBase(innerLabel)
            : '';
        const candidates = [
            ...buildTranslationCandidates(preferred),
            ...buildTranslationCandidates(base)
        ].filter((v, i, arr) => v && arr.indexOf(v) === i);
        if (!candidates.length) return null;

        for (const cand of candidates) {
            try {
                const resp = await fetch(`/prompt-composer/api/tag-translate?tag=${encodeURIComponent(cand)}`);
                if (!resp.ok) continue;
                const data = await resp.json();
                const jp = (data && data.jp) ? String(data.jp).trim() : '';
                if (jp) return jp;
            } catch (_) {
                // ignore and try next candidate
            }
        }
        return null;
    }

    function inferSourceTypeAfterEdit(parsed, prevMeta) {
        if (parsed && parsed.loraParsed) return 'lora';
        const text = String((parsed && (parsed.emittedText || parsed.label)) || '').trim();
        if (/^__[^_].*__$/.test(text)) return 'wildcard';
        const prev = (prevMeta && prevMeta.sourceType) ? prevMeta.sourceType : 'manual';
        if (prev === 'embedding') return 'embedding';
        if (prev === 'lora') return 'manual';
        if (prev === 'wildcard') return 'manual';
        return prev;
    }

    async function updateTokenFromRaw(blockId, tokenIdx, rawText) {
        const block = findBlock(blockId);
        if (!block || tokenIdx < 0 || tokenIdx >= block.tokens.length) {
            renderBlocks();
            return;
        }

        const token = block.tokens[tokenIdx];
        const prevMeta = { sourceType: token.sourceType || 'manual', isTrigger: token.isTrigger === true };

        const parsed = parseComposerTokenSlice(rawText);
        if (!parsed) {
            renderBlocks();
            return;
        }

        token.text = parsed.emittedText;
        token.label = parsed.label;
        token.weight = parsed.weight;
        jpLookupTried.delete(token.id);

        const nextSource = inferSourceTypeAfterEdit(parsed, prevMeta);
        token.sourceType = nextSource;
        token.isTrigger = prevMeta.isTrigger === true && nextSource === 'lora';
        if (nextSource !== 'lora') {
            token.previewUrl = null;
        }

        token.jp = await fetchComposerTagJp(parsed.label, parsed, parsed.emittedText);
        if (!token.jp) {
            const key = getTokenJpLookupKey(token);
            if (key) jpLookupTried.set(token.id, key);
        }
        renderBlocks();
    }

    function startTokenInlineEdit(blockId, tokenIdx) {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;

        hideTagSuggest();

        const tokenEl = container.querySelector(
            `.pc-token[data-block-id="${blockId}"][data-token-idx="${tokenIdx}"]`
        );
        const block = findBlock(blockId);
        const tok = block && block.tokens[tokenIdx];
        if (!tokenEl || !tok) return;
        if (tokenEl.classList.contains('pc-token-editing')) return;

        tokenEl.classList.add('pc-token-editing');
        tokenEl.draggable = false;

        tokenEl.querySelectorAll('.pc-token-source-badge, .pc-token-label, .pc-token-edit, .pc-token-remove').forEach(el => {
            el.style.display = 'none';
        });

        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'pc-token-edit-input';
        inp.value = tok.text || '';
        inp.autocomplete = 'off';
        inp.title = '編集 — Enter で確定 / Esc で取消';
        inp.setAttribute('aria-label', 'タグ編集');

        tokenEl.appendChild(inp);
        inp.focus();
        inp.select();

        inp.addEventListener('click', (e) => e.stopPropagation());
        inp.addEventListener('mousedown', (e) => e.stopPropagation());

        let editFinishMode = null;

        inp.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();
                editFinishMode = 'commit';
                updateTokenFromRaw(blockId, tokenIdx, inp.value).finally(() => {
                    editFinishMode = null;
                });
            } else if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                editFinishMode = 'escape';
                renderBlocks();
                setTimeout(() => { editFinishMode = null; }, 0);
            }
        });

        const originalText = (tok.text || '');

        inp.addEventListener('blur', () => {
            setTimeout(() => {
                if (editFinishMode === 'commit' || editFinishMode === 'escape') return;
                if (!inp.isConnected) return;
                if (!tokenEl.classList.contains('pc-token-editing')) return;

                const nextTrim = (inp.value || '').trim();
                const origTrim = (originalText || '').trim();
                if (nextTrim === origTrim) {
                    renderBlocks();
                    return;
                }
                if (!nextTrim) {
                    renderBlocks();
                    return;
                }
                updateTokenFromRaw(blockId, tokenIdx, inp.value);
            }, 0);
        });
    }

    function addTokenFromInput(blockId, rawText) {
        // If contains separators, split into multiple tokens (one render)
        if (/[,\n、]/.test(rawText)) {
            const block = findBlock(blockId);
            if (!block) return;
            beginBatchUpdate();
            try {
                rawText
                    .split(/[,\n、]/)
                    .map(t => t.trim())
                    .filter(t => t.length > 0)
                    .forEach(part => {
                        const parsed = parseComposerTokenSlice(part);
                        if (!parsed) return;
                        pushTokenToBlock(block, parsed.label, parsed.emittedText, {
                            weight: parsed.weight,
                            sourceType: 'manual',
                            isTrigger: false
                        });
                    });
            } finally {
                endBatchUpdate();
            }
            scheduleJpBackfill(120);
            return;
        }

        (async () => {
            const parsed = parseComposerTokenSlice(rawText);
            if (!parsed) return;

            const jp = await fetchComposerTagJp(parsed.label, parsed, parsed.emittedText);

            addToken(blockId, parsed.label, parsed.emittedText, {
                weight: parsed.weight,
                sourceType: 'manual',
                isTrigger: false,
                jp: jp || null
            });
            scheduleJpBackfill(120);
        })();
    }

    function removeToken(blockId, tokenIdx) {
        const block = findBlock(blockId);
        if (block && tokenIdx >= 0 && tokenIdx < block.tokens.length) {
            block.tokens.splice(tokenIdx, 1);
            renderBlocks();
        }
    }

    function toggleTokenHidden(blockId, tokenIdx) {
        const block = findBlock(blockId);
        if (!block || tokenIdx < 0 || tokenIdx >= block.tokens.length) return;
        const token = block.tokens[tokenIdx];
        if (!token) return;
        token.hidden = token.hidden !== true;
        renderBlocks();
    }

    function clearAllTokens() {
        if (!confirm('すべてのブロックのトークンをクリアしますか？')) return;
        blocks.forEach(b => b.tokens = []);
        negativeBlocks.forEach(b => b.tokens = []);
        renderBlocks();
    }

    function renameBlockLabel(blockId) {
        const block = findBlock(blockId);
        if (!block) return;
        const current = (block.label || '').trim();
        const next = prompt('ブロック名を編集:', current || '');
        if (next == null) return; // cancelled
        const trimmed = String(next).trim();
        if (!trimmed) return;
        block.label = trimmed;
        renderBlocks();
    }

    function clearBlockTokens(blockId) {
        const block = findBlock(blockId);
        if (!block || !Array.isArray(block.tokens) || block.tokens.length === 0) return;
        if (!confirm(`「${block.label}」のタグをすべて削除しますか？`)) return;
        block.tokens = [];
        renderBlocks();
    }

    function clearBlockTokensSilent(blockId) {
        const block = findBlock(blockId);
        if (!block) return;
        block.tokens = [];
    }

    function findBlockByType(type, useNegative = false) {
        const list = useNegative ? negativeBlocks : blocks;
        return list.find(b => b.type === type && b.enabled !== false)
            || list.find(b => b.type === type);
    }

    function fillBlockFromText(blockId, text) {
        const raw = String(text || '').trim();
        if (!raw || !blockId) return;
        const block = findBlock(blockId);
        if (!block) return;
        const parts = raw.split(/[,\n、]/).map(t => t.trim()).filter(Boolean);
        if (!parts.length) return;

        const applyParts = () => {
            parts.forEach(part => {
                const parsed = parseComposerTokenSlice(part);
                if (!parsed) return;
                pushTokenToBlock(block, parsed.label, parsed.emittedText, {
                    weight: parsed.weight,
                    sourceType: 'ips',
                    isTrigger: false
                });
            });
        };

        if (batchUpdateDepth > 0) {
            applyParts();
        } else {
            beginBatchUpdate();
            try {
                applyParts();
            } finally {
                endBatchUpdate();
            }
        }
    }

    /**
     * Import prompt slots from Infinite Prompt Studio (IPS).
     * @param {object} payload
     * @param {'replace'|'append'} [payload.mode]
     * @param {object} [payload.slots] quality, character, outfit, environment, pose, r18, lora
     * @param {string} [payload.negative]
     * @param {object} [payload.options] includeQuality, onlySlots, switchTab
     */
    function importFromIPS(payload) {
        if (!payload || typeof payload !== 'object') {
            return { ok: false, error: 'invalid payload' };
        }

        const mode = payload.mode === 'append' ? 'append' : 'replace';
        const slots = payload.slots || {};
        const opts = payload.options || {};
        const includeQuality = opts.includeQuality === true;
        const onlySlots = Array.isArray(opts.onlySlots) ? opts.onlySlots : null;
        const onlyBlockTypes = Array.isArray(opts.onlyBlockTypes) ? opts.onlyBlockTypes : null;

        const shouldImport = (key) => !onlySlots || onlySlots.includes(key);
        const shouldImportBlock = (blockTypes) => {
            if (!onlyBlockTypes) return true;
            const list = Array.isArray(blockTypes) ? blockTypes : [blockTypes];
            return list.some(t => onlyBlockTypes.includes(t));
        };

        const slotPlan = [
            { key: 'quality', blockTypes: ['quality', 'style'], targetType: 'quality', enabled: includeQuality && shouldImport('quality') && shouldImportBlock(['quality', 'style']) },
            { key: 'character', blockTypes: ['character', 'subject', 'appearance'], targetType: 'character', enabled: shouldImport('character') && shouldImportBlock(['character', 'subject', 'appearance']) },
            { key: 'outfit', blockTypes: ['outfit'], targetType: 'outfit', enabled: shouldImport('outfit') && shouldImportBlock('outfit') },
            { key: 'environment', blockTypes: ['background', 'lighting'], targetType: 'background', enabled: shouldImport('environment') && shouldImportBlock(['background', 'lighting']) },
            { key: 'pose', blockTypes: ['composition', 'expression'], targetType: 'composition', enabled: shouldImport('pose') && shouldImportBlock(['composition', 'expression']) },
            { key: 'r18', blockTypes: ['composition', 'expression'], targetType: 'composition', enabled: shouldImport('r18') && shouldImportBlock(['composition', 'expression']) },
            { key: 'lora', blockTypes: ['lora', 'embedding'], targetType: 'lora', enabled: shouldImport('lora') && shouldImportBlock(['lora', 'embedding']) }
        ];

        let imported = 0;

        beginBatchUpdate();
        try {
        for (const plan of slotPlan) {
            if (!plan.enabled) continue;
            const text = String(slots[plan.key] || '').trim();
            if (!text) continue;

            const block = findBlockByType(plan.targetType);
            if (!block) continue;

            const isCompositionR18 = plan.key === 'r18';
            if (mode === 'replace' && !isCompositionR18) {
                clearBlockTokensSilent(block.id);
            } else if (mode === 'replace' && isCompositionR18 && plan.key === 'r18') {
                const poseText = String(slots.pose || '').trim();
                if (!poseText) {
                    clearBlockTokensSilent(block.id);
                }
            }

            fillBlockFromText(block.id, text);
            imported += 1;
        }

        if (shouldImport('negative') && payload.negative != null) {
            const negText = String(payload.negative || '').trim();
            const negBlock = findBlockByType('negative', true);
            if (negBlock) {
                if (mode === 'replace') clearBlockTokensSilent(negBlock.id);
                if (negText) {
                    fillBlockFromText(negBlock.id, negText);
                    imported += 1;
                }
            }
        }
        } finally {
            endBatchUpdate();
        }

        scheduleJpBackfill(200);

        try {
            window.dispatchEvent(new CustomEvent('pc:ips-imported', { detail: { imported, payload } }));
        } catch (_) {}

        return { ok: true, imported };
    }

    function deleteBlock(blockId) {
        if (!blockId) return;
        const block = findBlock(blockId);
        if (!block) return;
        if (!confirm(`「${block.label}」欄を削除しますか？`)) return;

        const posIdx = blocks.findIndex(b => b.id === blockId);
        if (posIdx >= 0) {
            blocks.splice(posIdx, 1);
            blocks.forEach((b, i) => b.order = i);
            renderBlocks();
            return;
        }

        const negIdx = negativeBlocks.findIndex(b => b.id === blockId);
        if (negIdx >= 0) {
            negativeBlocks.splice(negIdx, 1);
            negativeBlocks.forEach((b, i) => b.order = i);
            renderBlocks();
        }
    }

    function insertSpecialToken(kind) {
        const blocks = window.PromptComposer.blocks || [];
        let target = null;

        // 1) use last active block if available
        const activeId = window.PromptComposerActiveBlockId;
        if (activeId) {
            target = blocks.find(b => b.id === activeId);
        }

        // 2) otherwise subject block
        if (!target) {
            target = blocks.find(b => b.type === 'subject');
        }

        // 3) otherwise first enabled positive block
        if (!target) {
            target = blocks.find(b => b.enabled) || blocks[0];
        }
        if (!target) return;

        addToken(target.id, kind, kind, {
            sourceType: 'manual',
            isTrigger: false
        });
    }

    async function autoFormatBlocks() {
        // 1. Remove duplicate tokens (keeping first occurrence)
        const seenTokens = new Set();
        blocks.forEach(block => {
            if (!block.enabled) return;
            block.tokens = block.tokens.filter(token => {
                const norm = token.text.toLowerCase().trim();
                // If it's a LoRA or Embedding token, don't auto-dedupe just to be safe
                if (token.sourceType === 'lora' || token.sourceType === 'embedding') return true;
                if (seenTokens.has(norm)) return false;
                seenTokens.add(norm);
                return true;
            });
        });

        // 2. Move blocks to match selected profile order
        await sortBlocksByProfile();
        
        renderBlocks();
    }

    // ===== Templates =====
    function applyTemplate(templateName) {
        if (!confirm(`テンプレート「${templateName}」を現在のブロックに追加しますか？`)) return;

        let templateTokens = [];

        if (templateName === '基本: キャラ立ち絵') {
            currentOrderProfile = 'character_focus';
            templateTokens = [
                { block: 'quality', label: 'masterpiece', text: 'masterpiece' },
                { block: 'quality', label: 'best quality', text: 'best quality' },
                { block: 'character', label: '1girl', text: '1girl' },
                { block: 'character', label: 'solo', text: 'solo' },
                { block: 'composition', label: 'cowboy shot', text: 'cowboy shot' },
                { block: 'composition', label: 'looking at viewer', text: 'looking at viewer' },
                { block: 'background', label: 'simple background', text: 'simple background' }
            ];
            negativeBlocks[0].tokens.push({ id: generateId(), label: 'lowres', text: 'lowres', sourceType: 'manual' });
            negativeBlocks[0].tokens.push({ id: generateId(), label: 'bad anatomy', text: 'bad anatomy', sourceType: 'manual' });
        } else if (templateName === '基本: 風景・背景') {
            currentOrderProfile = 'background_focus';
            templateTokens = [
                { block: 'quality', label: 'masterpiece', text: 'masterpiece' },
                { block: 'quality', label: 'best quality', text: 'best quality' },
                { block: 'quality', label: 'highly detailed', text: 'highly detailed' },
                { block: 'subject', label: 'scenery', text: 'scenery' },
                { block: 'subject', label: 'no humans', text: 'no humans' },
                { block: 'background', label: 'outdoors', text: 'outdoors' }
            ];
            blocks.find(b => b.type === 'character').enabled = false;
            blocks.find(b => b.type === 'appearance').enabled = false;
            blocks.find(b => b.type === 'outfit').enabled = false;
            blocks.find(b => b.type === 'expression').enabled = false;
        } else if (templateName === '複雑: キャラ＋背景') {
            currentOrderProfile = 'illustrious_standard';
            templateTokens = [
                { block: 'quality', label: 'masterpiece', text: 'masterpiece' },
                { block: 'quality', label: 'best quality', text: 'best quality' },
                { block: 'character', label: '1girl', text: '1girl' },
                { block: 'appearance', label: 'detailed eyes', text: 'detailed eyes' },
                { block: 'composition', label: 'depth of field', text: 'depth of field' },
                { block: 'background', label: 'detailed background', text: 'detailed background' },
                { block: 'lighting', label: 'cinematic lighting', text: 'cinematic lighting' }
            ];
        }

        // Apply tokens
        templateTokens.forEach(t => {
            const b = blocks.find(block => block.type === t.block);
            if (b && !b.tokens.some(token => token.text === t.text)) {
                b.enabled = true;
                b.tokens.push({
                    id: generateId(),
                    label: t.label,
                    text: t.text,
                    sourceType: 'manual'
                });
            }
        });

        // Sync order-profile tree / Gradio mirror with currentOrderProfile
        const profileRoot = document.getElementById('pc_order_profile');
        if (profileRoot && currentOrderProfile) {
            const id = String(currentOrderProfile);
            const items = profileRoot.querySelectorAll('.pc-file-tree-item[data-profile-id]');
            let matched = null;
            items.forEach(el => {
                if (el.getAttribute('data-profile-id') === id) matched = el;
            });
            if (matched) {
                matched.click();
            } else {
                const selectEl = profileRoot.querySelector('select');
                if (selectEl) {
                    selectEl.value = currentOrderProfile;
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        }

        sortBlocksByProfile(); // renderBlocks is called inside
    }

    // ===== Insert from Asset Browser =====
    function insertAsset(asset) {
        // Prefer last active (focused) block, so users can switch
        // between Positive/Negative insertion by clicking the input field.
        const activeId = window.PromptComposerActiveBlockId;
        let targetBlock = null;
        if (activeId) {
            targetBlock = blocks.find(b => b.id === activeId) || negativeBlocks.find(b => b.id === activeId);
        }

        const blockType = asset.preferredBlock || (asset.type === 'lora' ? 'lora' : 'embedding');
        if (!targetBlock) {
            targetBlock = blocks.find(b => b.type === blockType);
        }
        
        if (!targetBlock) {
            targetBlock = blocks.find(b => b.type === asset.type);
        }
        if (!targetBlock) {
            targetBlock = blocks[blocks.length - 1];
        }
        if (!targetBlock) return;

        // Use filename for display label (less ambiguous than displayName)
        const label = asset.name || asset.displayName;
        const text = asset.insertTemplate || asset.name;
        
        // Check for duplicate
        if (targetBlock.tokens.some(t => t.text === text)) {
            console.log('[Prompt Composer] Asset already in block:', text);
            return;
        }

        // Embeddings: single token only (no trigger words)
        if (asset.type === 'embedding') {
            addToken(targetBlock.id, label, text, {
                weight: asset.defaultWeight,
                sourceType: asset.type,
                isTrigger: false,
                previewUrl: asset.previewUrl || null
            });
            return;
        }

        // LoRA: insert LoRA then trigger words immediately after it in the SAME block
        const loraTok = {
            id: generateId(),
            label: label,
            text: text || label,
            weight: (typeof asset.defaultWeight === 'number' && !Number.isNaN(asset.defaultWeight)) ? asset.defaultWeight : null,
            sourceType: 'lora',
            isTrigger: false,
            hidden: false,
            previewUrl: asset.previewUrl || null,
            jp: null
        };
        const insertAt = targetBlock.tokens.length;
        targetBlock.tokens.splice(insertAt, 0, loraTok);

        let at = insertAt + 1;
        if (asset.triggerWords && asset.triggerWords.length > 0) {
            asset.triggerWords.forEach(tw => {
                if (!tw || targetBlock.tokens.some(t => t.text === tw)) return;
                const t = {
                    id: generateId(),
                    label: tw,
                    text: tw,
                    weight: null,
                    sourceType: asset.type,
                    isTrigger: true,
                    hidden: false,
                    previewUrl: null,
                    jp: null
                };
                targetBlock.tokens.splice(at, 0, t);
                at++;
            });
        }

        renderBlocks();
        scheduleJpBackfill(140);
    }

    // ===== Drag and Drop =====
    function getComposerScrollContainer() {
        const byId = document.getElementById('pc_composer_area');
        if (byId) {
            const oy = window.getComputedStyle(byId).overflowY;
            if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') return byId;
        }
        const host = document.getElementById('pc_blocks_container');
        let el = host && host.parentElement;
        while (el && el !== document.documentElement) {
            const oy = window.getComputedStyle(el).overflowY;
            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay') && el.scrollHeight > el.clientHeight + 1) {
                return el;
            }
            el = el.parentElement;
        }
        return byId || null;
    }

    function onDocumentDragOverBlockDragAutoScroll(e) {
        if (!draggedBlock || draggedToken) return;
        const scroller = getComposerScrollContainer();
        if (!scroller) return;
        const maxScroll = scroller.scrollHeight - scroller.clientHeight;
        if (maxScroll <= 0) return;
        const rect = scroller.getBoundingClientRect();
        const zone = 64;
        const stepBase = Math.round(scroller.clientHeight * 0.07);
        const step = Math.max(10, Math.min(32, stepBase));
        if (e.clientY < rect.top + zone) {
            const dist = rect.top + zone - e.clientY;
            const factor = Math.min(2.2, 1 + dist / zone);
            scroller.scrollTop = Math.max(0, scroller.scrollTop - Math.round(step * factor));
        } else if (e.clientY > rect.bottom - zone) {
            const dist = e.clientY - (rect.bottom - zone);
            const factor = Math.min(2.2, 1 + dist / zone);
            scroller.scrollTop = Math.min(maxScroll, scroller.scrollTop + Math.round(step * factor));
        }
    }

    function onDragStart(e) {
        const header = e.target.closest('.pc-block-header-draggable');
        if (!header) return;
        draggedBlock = header.closest('.pc-block');
        if (draggedBlock) {
            draggedBlock.classList.add('pc-block-dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', draggedBlock.dataset.blockId);
        }
    }

    function onDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        
        const target = e.target.closest('.pc-block');
        if (target && target !== draggedBlock) {
            const rect = target.getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            
            target.classList.remove('pc-block-drag-above', 'pc-block-drag-below');
            if (e.clientY < midY) {
                target.classList.add('pc-block-drag-above');
            } else {
                target.classList.add('pc-block-drag-below');
            }
        }
    }

    function onDragEnd(e) {
        document.querySelectorAll('.pc-block').forEach(el => {
            el.classList.remove('pc-block-dragging', 'pc-block-drag-above', 'pc-block-drag-below');
        });
        draggedBlock = null;
    }

    function onDrop(e) {
        e.preventDefault();
        const targetEl = e.target.closest('.pc-block');
        if (!targetEl || !draggedBlock) return;

        const dragId = draggedBlock.dataset.blockId;
        const dropId = targetEl.dataset.blockId;
        const isNegative = draggedBlock.dataset.isNegative === 'true';
        
        const list = isNegative ? negativeBlocks : blocks;
        const dragIdx = list.findIndex(b => b.id === dragId);
        const dropIdx = list.findIndex(b => b.id === dropId);

        if (dragIdx === -1 || dropIdx === -1 || dragIdx === dropIdx) return;

        // Move block
        const [moved] = list.splice(dragIdx, 1);
        list.splice(dropIdx, 0, moved);

        // Update order
        list.forEach((b, i) => b.order = i);

        renderBlocks();
    }

    // ===== Sorting =====
    async function sortBlocksByProfile(profileIdOverride = null) {
        // Prefer explicit caller-provided id, then in-memory current profile.
        // Avoid depending on Gradio dropdown DOM value because some environments
        // render tuple-like option labels/values and can break reads.
        const profileId = profileIdOverride || currentOrderProfile;
        if (!profileId) return;

        try {
            const resp = await fetch(`/prompt-composer/api/order-profiles/${profileId}`);
            if (!resp.ok) throw new Error('Profile not found');
            const profile = await resp.json();
            const orderList = profile.order || [];

            blocks.sort((a, b) => {
                const ai = orderList.indexOf(a.type);
                const bi = orderList.indexOf(b.type);
                return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
            });

            blocks.forEach((b, i) => b.order = i);
            renderBlocks();
        } catch (err) {
            console.warn('[Prompt Composer] Sort failed:', err);
        }
    }

    function showBlockReorderModal() {
        const existing = document.getElementById('pc_block_reorder_modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'pc_block_reorder_modal';
        overlay.className = 'pc-reorder-modal-overlay';
        overlay.innerHTML = `
            <div class="pc-reorder-modal" role="dialog" aria-modal="true" aria-label="ブロック順序入替え">
                <div class="pc-reorder-modal-head">
                    <div class="pc-reorder-modal-title">順序入替え</div>
                    <button type="button" class="pc-reorder-modal-close" title="閉じる" aria-label="閉じる">×</button>
                </div>
                <div class="pc-reorder-modal-hint">ドラッグしてブロックの表示順を変更できます</div>
                <div class="pc-reorder-modal-body">
                    <div class="pc-reorder-section">
                        <div class="pc-reorder-section-label">Positive Prompt</div>
                        <div class="pc-reorder-list" data-side="positive"></div>
                    </div>
                    <div class="pc-reorder-section">
                        <div class="pc-reorder-section-label">Negative Prompt</div>
                        <div class="pc-reorder-list" data-side="negative"></div>
                    </div>
                </div>
                <div class="pc-reorder-modal-foot">
                    <button type="button" class="pc-reorder-profile-sort" title="現在の順序プロファイル推奨順に並び替え">推奨順に整形</button>
                    <button type="button" class="pc-reorder-modal-done">完了</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const posList = overlay.querySelector('.pc-reorder-list[data-side="positive"]');
        const negList = overlay.querySelector('.pc-reorder-list[data-side="negative"]');

        const fillList = (listEl, list) => {
            if (!listEl) return;
            listEl.innerHTML = list.map((b, idx) => `
                <div class="pc-reorder-item" draggable="true" data-block-id="${escapeHtml(b.id)}" data-idx="${idx}">
                    <span class="pc-reorder-handle" aria-hidden="true">⠿</span>
                    <span class="pc-reorder-item-name">${escapeHtml(b.label || b.type || b.id)}</span>
                    <span class="pc-reorder-item-count">${(b.tokens || []).length}</span>
                </div>
            `).join('') || '<div class="pc-reorder-empty">ブロックなし</div>';
        };

        const refreshLists = () => {
            fillList(posList, blocks);
            fillList(negList, negativeBlocks);
            bindListDnD(posList, false);
            bindListDnD(negList, true);
        };

        let dragEl = null;

        const bindListDnD = (listEl, isNegative) => {
            if (!listEl) return;
            listEl.querySelectorAll('.pc-reorder-item').forEach(item => {
                item.addEventListener('dragstart', (e) => {
                    dragEl = item;
                    item.classList.add('is-dragging');
                    try {
                        e.dataTransfer.effectAllowed = 'move';
                        e.dataTransfer.setData('text/plain', item.dataset.blockId || '');
                    } catch (_) { /* ignore */ }
                });
                item.addEventListener('dragend', () => {
                    item.classList.remove('is-dragging');
                    listEl.querySelectorAll('.pc-reorder-item').forEach(el => {
                        el.classList.remove('pc-reorder-drag-above', 'pc-reorder-drag-below');
                    });
                    dragEl = null;
                });
                item.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    if (!dragEl || dragEl === item || dragEl.parentElement !== listEl) return;
                    const rect = item.getBoundingClientRect();
                    const before = (e.clientY - rect.top) < rect.height / 2;
                    item.classList.toggle('pc-reorder-drag-above', before);
                    item.classList.toggle('pc-reorder-drag-below', !before);
                });
                item.addEventListener('dragleave', () => {
                    item.classList.remove('pc-reorder-drag-above', 'pc-reorder-drag-below');
                });
                item.addEventListener('drop', (e) => {
                    e.preventDefault();
                    if (!dragEl || dragEl === item || dragEl.parentElement !== listEl) return;
                    const rect = item.getBoundingClientRect();
                    const before = (e.clientY - rect.top) < rect.height / 2;
                    const list = isNegative ? negativeBlocks : blocks;
                    const fromId = dragEl.dataset.blockId;
                    const toId = item.dataset.blockId;
                    const fromIdx = list.findIndex(b => b.id === fromId);
                    if (fromIdx < 0) return;
                    const [moved] = list.splice(fromIdx, 1);
                    let nextIdx = list.findIndex(b => b.id === toId);
                    if (nextIdx < 0) nextIdx = list.length;
                    else if (!before) nextIdx += 1;
                    list.splice(nextIdx, 0, moved);
                    list.forEach((b, i) => { b.order = i; });
                    renderBlocks();
                    refreshLists();
                });
            });
        };

        refreshLists();

        const close = () => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        };
        const closeBtn = overlay.querySelector('.pc-reorder-modal-close');
        const doneBtn = overlay.querySelector('.pc-reorder-modal-done');
        const profileSortBtn = overlay.querySelector('.pc-reorder-profile-sort');
        if (closeBtn) closeBtn.addEventListener('click', close);
        if (doneBtn) doneBtn.addEventListener('click', close);
        if (profileSortBtn) {
            profileSortBtn.addEventListener('click', async () => {
                await sortBlocksByProfile();
                refreshLists();
            });
        }
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });
        document.addEventListener('keydown', function onEsc(ev) {
            if (ev.key === 'Escape') {
                document.removeEventListener('keydown', onEsc);
                close();
            }
        });
    }

    // ===== Final Prompt Generation =====
    function buildPromptString(tokenTexts) {
        const parts = Array.isArray(tokenTexts) ? tokenTexts : [];
        let out = '';
        let lastWasSpecial = false;
        for (const raw of parts) {
            const t = (raw || '').trim();
            if (!t) continue;
            const isSpecial = (t === 'BREAK' || t === 'AND');
            if (isSpecial) {
                if (out && !out.endsWith(' ')) out += ' ';
                out += t;
                out += ' ';
                lastWasSpecial = true;
            } else {
                if (!out) {
                    out = t;
                } else if (lastWasSpecial) {
                    // after BREAK/AND, connect with a space (no comma)
                    if (!out.endsWith(' ')) out += ' ';
                    out += t;
                } else {
                    out += ', ' + t;
                }
                lastWasSpecial = false;
            }
        }
        // normalize spaces
        out = out.replace(/\s+/g, ' ').trim();
        // extra safety: remove commas adjacent to special tokens
        out = out.replace(/,\s*(BREAK|AND)\s*,/g, ' $1 ').replace(/,\s*(BREAK|AND)\b/g, ' $1').replace(/\b(BREAK|AND)\s*,/g, '$1 ');
        out = out.replace(/\s+/g, ' ').trim();
        return out;
    }

    function updateFinalPrompt() {
        const promptParts = [];

        blocks.forEach(block => {
            if (!block.enabled || block.tokens.length === 0) return;
            
            block.tokens.forEach(token => {
                if (token.hidden === true) return;
                promptParts.push(token.text);
            });
        });

        const finalPrompt = buildPromptString(promptParts);
        
        // Negative
        const negParts = [];
        negativeBlocks.forEach(block => {
            if (!block.enabled || block.tokens.length === 0) return;
            block.tokens.forEach(token => {
                if (token.hidden === true) return;
                negParts.push(token.text);
            });
        });
        const finalNegative = buildPromptString(negParts);

        // Update Gradio textboxes
        setGradioValue('txt2img_prompt', finalPrompt);
        setGradioValue('txt2img_neg_prompt', finalNegative);
        setGradioValue('pc_final_prompt', finalPrompt);
        setGradioValue('pc_final_negative', finalNegative);
    }

    // ===== Preset Integration =====
    function getState() {
        return {
            blocks: blocks.map(b => ({
                type: b.type,
                label: b.label,
                order: b.order,
                enabled: b.enabled,
                tokens: b.tokens.map(t => ({
                    label: t.label,
                    text: t.text,
                    weight: t.weight,
                    sourceType: t.sourceType,
                    isTrigger: t.isTrigger === true,
                    hidden: t.hidden === true,
                    jp: t.jp || null
                }))
            })),
            negativeBlocks: negativeBlocks.map(b => ({
                type: b.type,
                label: b.label,
                order: b.order,
                enabled: b.enabled,
                tokens: b.tokens.map(t => ({
                    label: t.label,
                    text: t.text,
                    weight: t.weight,
                    sourceType: t.sourceType,
                    isTrigger: t.isTrigger === true,
                    hidden: t.hidden === true,
                    jp: t.jp || null
                }))
            })),
            orderProfile: currentOrderProfile,
            characterMemo: getCharacterMemo(),
            memoFormat: getCharacterMemo().trim() ? 'markdown' : ''
        };
    }

    function loadState(state) {
        if (!state) return;

        const nextMemo = state.characterMemo != null
            ? state.characterMemo
            : (state.memo != null ? state.memo : '');
        setCharacterMemo(nextMemo, { silent: true });

        if (state.blocks && Array.isArray(state.blocks)) {
            blocks = state.blocks.map(b => ({
                id: generateId(),
                type: b.type,
                label: b.label || DEFAULT_BLOCKS.find(d => d.type === b.type)?.label || b.type,
                order: b.order,
                enabled: b.enabled !== false,
                tokens: (b.tokens || []).map(t => ({
                    id: generateId(),
                    label: t.label,
                    text: t.text,
                    weight: t.weight,
                    sourceType: t.sourceType || 'manual',
                    isTrigger: t.isTrigger === true,
                    hidden: t.hidden === true,
                    jp: t.jp || null
                }))
            }));
        }

        if (state.negativeBlocks && Array.isArray(state.negativeBlocks)) {
            negativeBlocks = state.negativeBlocks.map(b => ({
                id: generateId(),
                type: b.type,
                label: b.label || '🚫 Negative',
                order: b.order,
                enabled: b.enabled !== false,
                tokens: (b.tokens || []).map(t => ({
                    id: generateId(),
                    label: t.label,
                    text: t.text,
                    weight: t.weight,
                    sourceType: t.sourceType || 'manual',
                    isTrigger: t.isTrigger === true,
                    hidden: t.hidden === true,
                    jp: t.jp || null
                }))
            }));
        }

        if (state.orderProfile) {
            currentOrderProfile = state.orderProfile;
        }

        // Best-effort: backfill missing JP translations for restored tokens
        // (e.g., when upgrading from older autosave/preset formats).
        setTimeout(() => {
            try { scheduleJpBackfill(60); } catch (_) {}
        }, 50);

        renderBlocks();
        setupCharacterMemoListener();
        setupCharacterMemoTabs();
        setCharacterMemo(characterMemo, { silent: true });
        if (characterMemoMode === 'preview') {
            updateCharacterMemoPreview();
        }
    }

    function scheduleJpBackfill(delayMs = 80) {
        clearTimeout(jpBackfillTimer);
        jpBackfillTimer = setTimeout(() => {
            backfillMissingJp({ batchSize: 120, continueUntilDone: true }).catch(() => {});
        }, delayMs);
    }

    function patchTokenJpInDom(tokenId, jp) {
        if (!tokenId || !jp) return;
        const selector = `.pc-token[data-token-id="${CSS.escape(String(tokenId))}"]`;
        document.querySelectorAll(selector).forEach((tokenEl) => {
            let jpEl = tokenEl.querySelector('.pc-token-jp');
            if (jpEl) {
                jpEl.textContent = jp;
                return;
            }
            const label = tokenEl.querySelector('.pc-token-label');
            if (!label) return;
            jpEl = document.createElement('span');
            jpEl.className = 'pc-token-jp';
            jpEl.textContent = jp;
            label.appendChild(jpEl);
        });
    }

    async function backfillMissingJp(options = {}) {
        const batchSize = Math.max(1, Number(options.batchSize || 120));
        const continueUntilDone = options.continueUntilDone !== false;
        const allBlocks = [...blocks, ...negativeBlocks];
        const missing = [];
        allBlocks.forEach(b => {
            (b.tokens || []).forEach(t => {
                if (t && !t.jp && t.text && typeof t.text === 'string') {
                    const key = getTokenJpLookupKey(t);
                    if (!key) return;
                    // Do not retry the same key forever when dictionary has no translation.
                    if (jpLookupTried.get(t.id) === key) return;
                    missing.push(t);
                }
            });
        });

        let updated = false;
        for (const t of missing.slice(0, batchSize)) {
            const jp = await fetchComposerTagJp(t.label || t.text, null, t.text);
            if (jp) {
                t.jp = jp;
                jpLookupTried.delete(t.id);
                patchTokenJpInDom(t.id, jp);
                updated = true;
            } else {
                const key = getTokenJpLookupKey(t);
                if (key) jpLookupTried.set(t.id, key);
            }
        }
        if (updated) scheduleAutoSave();

        const remaining = missing.length - Math.min(batchSize, missing.length);
        if (continueUntilDone && remaining > 0) {
            scheduleJpBackfill(120);
        }
    }

    // ===== Add Block Dialog =====
    function chooseAddBlockSide() {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.style.position = 'fixed';
            overlay.style.inset = '0';
            overlay.style.background = 'rgba(0, 0, 0, 0.45)';
            overlay.style.display = 'flex';
            overlay.style.alignItems = 'center';
            overlay.style.justifyContent = 'center';
            overlay.style.zIndex = '10000';

            const box = document.createElement('div');
            box.style.minWidth = '300px';
            box.style.maxWidth = '92vw';
            box.style.padding = '14px';
            box.style.borderRadius = '10px';
            box.style.border = '1px solid rgba(255,255,255,0.16)';
            box.style.background = 'var(--background-fill-secondary, #2a2a2a)';
            box.style.color = 'var(--body-text-color, #eee)';
            box.innerHTML = `
                <div style="font-size:0.92em; font-weight:700; margin-bottom:10px;">追加先を選択してください</div>
                <div style="display:flex; gap:8px; margin-bottom:10px;">
                    <button type="button" class="pc-side-pick" data-side="positive" style="flex:1; padding:8px 10px; border-radius:8px; border:1px solid var(--border-color-primary,#555); background:rgba(118,185,237,0.18); color:var(--body-text-color,#eee); cursor:pointer;">Positive</button>
                    <button type="button" class="pc-side-pick" data-side="negative" style="flex:1; padding:8px 10px; border-radius:8px; border:1px solid var(--border-color-primary,#555); background:rgba(229,115,115,0.18); color:var(--body-text-color,#eee); cursor:pointer;">Negative</button>
                </div>
                <div style="text-align:right;">
                    <button type="button" class="pc-side-cancel" style="padding:6px 10px; border-radius:8px; border:1px solid var(--border-color-primary,#555); background:transparent; color:var(--body-text-color-subdued,#aaa); cursor:pointer;">キャンセル</button>
                </div>
            `;

            overlay.appendChild(box);
            document.body.appendChild(overlay);

            const close = (result) => {
                if (overlay && overlay.parentNode) {
                    overlay.parentNode.removeChild(overlay);
                }
                resolve(result);
            };

            box.querySelectorAll('.pc-side-pick').forEach(btn => {
                btn.addEventListener('click', () => close(btn.dataset.side || null));
            });
            const cancelBtn = box.querySelector('.pc-side-cancel');
            if (cancelBtn) cancelBtn.addEventListener('click', () => close(null));
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) close(null);
            });
        });
    }

    async function showAddBlockDialog() {
        const name = prompt('ブロック名を入力してください:');
        if (!name) return;

        const side = await chooseAddBlockSide();
        if (!side) return;
        const isNegative = (side === 'negative');

        const typeBase = name.toLowerCase().replace(/[^a-z0-9]/g, '_') || 'custom';
        const typeId = (isNegative ? `neg_${typeBase}` : typeBase);
        const target = isNegative ? negativeBlocks : blocks;

        target.push({
            id: generateId(),
            type: typeId,
            label: name,
            order: target.length,
            enabled: true,
            tokens: []
        });

        renderBlocks();
    }

    // ===== Utility =====
    function findBlock(blockId) {
        return blocks.find(b => b.id === blockId) 
            || negativeBlocks.find(b => b.id === blockId);
    }

    function isNegativeBlockId(blockId) {
        return negativeBlocks.some(b => b.id === blockId);
    }

    function generateId() {
        return Math.random().toString(36).substr(2, 9);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document;
    }

    function setGradioValue(elemId, value) {
        const container = appRoot().getElementById(elemId);
        if (!container) return;
        
        const textarea = container.querySelector('textarea');
        if (textarea) {
            const next = String(value ?? '');
            if (textarea.value === next) return;
            textarea.value = next;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
        }
        checkWarnings();
    }

    function dispatchStateChange(reason) {
        try {
            const detail = {
                reason: reason || 'unknown',
                activeBlockId: window.PromptComposerActiveBlockId || null
            };
            if (reason !== 'render') {
                detail.state = getState();
            }
            window.dispatchEvent(new CustomEvent('pc:state-changed', { detail }));
        } catch (_) {}
    }

    function dispatchActiveBlockChange(blockId) {
        try {
            window.dispatchEvent(new CustomEvent('pc:active-block-changed', {
                detail: { blockId: blockId || null }
            }));
        } catch (_) {}
    }

    function focusBlock(blockId) {
        if (!blockId) return false;
        const container = document.getElementById('pc_blocks_container');
        if (!container) return false;
        const blockEl = container.querySelector(`.pc-block[data-block-id="${blockId}"]`);
        if (!blockEl) return false;

        window.PromptComposerActiveBlockId = blockId;
        dispatchActiveBlockChange(blockId);

        const input = blockEl.querySelector('.pc-token-input');
        blockEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (input) {
            input.focus();
            return true;
        }
        return true;
    }

    /**
     * Apply caption text to a block by type (Vision tab).
     * @param {string} blockType e.g. outfit, appearance, character, background
     * @param {string} text
     * @param {'append'|'replace'} [mode]
     */
    function applyTextToBlockType(blockType, text, mode = 'append') {
        const block = findBlockByType(blockType);
        if (!block) return false;
        const raw = String(text || '').trim();
        if (!raw) return false;
        if (mode === 'replace') {
            clearBlockTokensSilent(block.id);
        }
        fillBlockFromText(block.id, raw);
        renderBlocks();
        focusBlock(block.id);
        return true;
    }

    // ===== Public API =====
    window.PromptComposer = {
        init,
        insertAsset,
        getState,
        loadState,
        addToken,
        addTokensBulk,
        beginBatchUpdate,
        endBatchUpdate,
        renderBlocks,
        sortBlocksByProfile,
        importFromIPS,
        focusBlock,
        findBlockByType,
        clearBlockTokensSilent,
        applyTextToBlockType,
        updateFinalPrompt,
        ensureOrderProfileManagerUI,
        get blocks() { return blocks; },
        get negativeBlocks() { return negativeBlocks; }
    };

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1000));
    } else {
        setTimeout(init, 1000);
    }

    // Also try on Gradio load
    onUiLoaded(() => setTimeout(init, 500));

    // Save on tab close / refresh (best-effort)
    window.addEventListener('beforeunload', () => {
        try {
            if (!window.PromptComposer) return;
            const state = window.PromptComposer.getState();
            const payload = { v: 1, savedAt: Date.now(), state };
            localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(payload));
        } catch (e) {
            // ignore
        }
    });

    function onUiLoaded(callback) {
        if (typeof gradio_config !== 'undefined') {
            callback();
        } else {
            const observer = new MutationObserver((mutations, obs) => {
                if (document.getElementById('pc_blocks_container')) {
                    obs.disconnect();
                    callback();
                }
            });
            function startBlocksObserver() {
                const target = (typeof document.body !== 'undefined' && document.body)
                    ? document.body
                    : document.documentElement;
                if (!(target instanceof Node)) {
                    requestAnimationFrame(startBlocksObserver);
                    return;
                }
                try {
                    observer.observe(target, { childList: true, subtree: true });
                } catch (_) {
                    requestAnimationFrame(startBlocksObserver);
                }
            }
            startBlocksObserver();
        }
    }

})();
