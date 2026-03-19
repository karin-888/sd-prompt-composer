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
    let blocks = [];
    let negativeBlocks = [];
    let currentOrderProfile = 'illustrious_standard';
    let draggedBlock = null;
    let draggedToken = null; // { tokenIds: string[], fromBlockId: string }
    let selectedTokenIds = new Set(); // multi-select support
    // NOTE: token selection is used for keyboard weight adjust (↑↓).

    // ===== Initialization =====
    function init() {
        // Wait for DOM
        const container = document.getElementById('pc_blocks_container');
        if (!container) {
            setTimeout(init, 500);
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
    function renderBlocks() {
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
            }

            const sourceBadge = badgeText
                ? `<span class="pc-token-source-badge ${badgeClass}">${badgeText}</span>`
                : '';

            const titleParts = [];
            if (isTW) titleParts.push('[TW]');
            if (isLoRA) titleParts.push('[LoRA]');
            if (isEmbedding) titleParts.push('[Embedding]');
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
                <span class="pc-token ${sourceClass} ${hiddenClass}" draggable="true" data-token-id="${token.id}" data-block-id="${block.id}" data-token-idx="${tidx}" title="${title}"${previewAttr}>
                    ${sourceBadge}
                    <span class="pc-token-label">
                        <span class="pc-token-label-text">${escapeHtml(token.label)}</span>
                        ${hasWeight ? `<span class="pc-token-weight ${weightClass}">${escapeHtml(weightStr)}</span>` : ''}
                        ${token.jp ? `<span class="pc-token-jp">${escapeHtml(token.jp)}</span>` : ''}
                    </span>
                    <button class="pc-token-remove" data-block-id="${block.id}" data-token-idx="${tidx}">×</button>
                </span>
            `;
        });

        return `
            <div class="pc-block ${enabledClass}" 
                 data-block-id="${block.id}" 
                 data-block-type="${block.type}"
                 data-is-negative="${isNegative}"
                 draggable="true">
                <div class="pc-block-header">
                    <span class="pc-block-drag-handle">⠿</span>
                    <button class="pc-block-toggle" data-block-id="${block.id}">${toggleIcon}</button>
                    <span class="pc-block-label">${block.label}</span>
                    <button class="pc-block-clear" data-block-id="${block.id}" title="この欄のタグをすべて削除">🧹</button>
                    <button class="pc-block-delete" data-block-id="${block.id}" title="この欄を削除">🗑️</button>
                    <span class="pc-block-count">${block.tokens.length}</span>
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
        // Sort blocks button
        const sortBtn = document.getElementById('pc_sort_blocks');
        if (sortBtn) {
            sortBtn.addEventListener('click', sortBlocksByProfile);
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

        // Order profile change
        const profileSelect = document.getElementById('pc_order_profile');
        if (profileSelect) {
            const selectEl = profileSelect.querySelector('select') || profileSelect.querySelector('input');
            if (selectEl) {
                selectEl.addEventListener('change', (e) => {
                    currentOrderProfile = e.target.value;
                    checkWarnings();
                });
            }
        }

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
        if (root.querySelector('.pc-order-profile-manager')) return;

        // Hide Gradio's original dropdown UI to avoid duplicated controls.
        // We keep it in DOM only as a silent compatibility mirror.
        const legacySelect = root.querySelector('select');
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
                <select class="pc-order-profile-select"></select>
                <button type="button" class="pc-order-profile-load" title="選択した順序を読込">読込</button>
            </div>
            <div class="pc-order-profile-row">
                <input type="text" class="pc-order-profile-name" placeholder="順序プロファイル名...">
                <button type="button" class="pc-order-profile-save" title="新規保存">保存</button>
                <button type="button" class="pc-order-profile-overwrite" title="上書き保存">上書き</button>
                <button type="button" class="pc-order-profile-delete" title="削除">削除</button>
            </div>
            <div class="pc-order-profile-hint">読込 / 保存 / 上書き / 削除（表示順のみ対象）</div>
        `;
        root.appendChild(wrap);

        const profileSelect = wrap.querySelector('.pc-order-profile-select');
        const nameInput = wrap.querySelector('.pc-order-profile-name');
        const loadBtn = wrap.querySelector('.pc-order-profile-load');
        const saveBtn = wrap.querySelector('.pc-order-profile-save');
        const overwriteBtn = wrap.querySelector('.pc-order-profile-overwrite');
        const delBtn = wrap.querySelector('.pc-order-profile-delete');

        const isBuiltinProfile = (id) => {
            return id === 'illustrious_standard' || id === 'character_focus' || id === 'background_focus';
        };

        const setCurrentProfile = (id) => {
            if (!id) return;
            currentOrderProfile = id;
            // keep gradio dropdown (if any) in sync
            const gradioSelect = root.querySelector('select');
            if (gradioSelect && Array.from(gradioSelect.options).some(o => o.value === id)) {
                gradioSelect.value = id;
                gradioSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };

        const getSelectedProfileId = () => {
            const id = profileSelect ? profileSelect.value : '';
            return id || currentOrderProfile;
        };

        const profileLabel = (profiles, id) => {
            const p = profiles[id] || {};
            return p.name || id;
        };

        const refreshSelect = async () => {
            const profiles = await fetchOrderProfiles();

            if (profileSelect) {
                const current = getSelectedProfileId();
                profileSelect.innerHTML = '';
                const builtins = ['illustrious_standard', 'character_focus', 'background_focus'];

                const addOpt = (id, label) => {
                    const opt = document.createElement('option');
                    opt.value = id;
                    opt.textContent = label || id;
                    profileSelect.appendChild(opt);
                };

                builtins.forEach(id => {
                    if (profiles[id]) addOpt(id, profileLabel(profiles, id));
                });
                Object.keys(profiles).forEach(id => {
                    if (builtins.includes(id)) return;
                    addOpt(id, `★ ${profileLabel(profiles, id)}`);
                });

                if (current && Array.from(profileSelect.options).some(o => o.value === current)) {
                    profileSelect.value = current;
                } else if (profileSelect.options.length > 0) {
                    profileSelect.selectedIndex = 0;
                }
                setCurrentProfile(profileSelect.value);
            }
        };

        // initial fill
        refreshSelect().catch(() => {});

        if (profileSelect) {
            profileSelect.addEventListener('change', () => {
                const id = profileSelect.value;
                setCurrentProfile(id);
            });
        }

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
                    await refreshSelect();
                    const savedId = data && data.id;
                    if (savedId && profileSelect && Array.from(profileSelect.options).some(o => o.value === savedId)) {
                        profileSelect.value = savedId;
                        setCurrentProfile(savedId);
                    }
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
                    await refreshSelect();
                    if (profileSelect && Array.from(profileSelect.options).some(o => o.value === id)) {
                        profileSelect.value = id;
                        setCurrentProfile(id);
                    }
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

    function attachBlockListeners() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;

        // Prevent block drag from stealing header button clicks
        container.querySelectorAll('.pc-block-toggle, .pc-block-clear, .pc-block-delete').forEach(btn => {
            btn.addEventListener('mousedown', (e) => {
                e.stopPropagation();
            });
        });

        // Toggle buttons
        container.querySelectorAll('.pc-block-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const blockId = e.currentTarget.dataset.blockId;
                toggleBlock(blockId);
            });
        });

        // Block label rename (dblclick)
        container.querySelectorAll('.pc-block-label').forEach(el => {
            el.addEventListener('dblclick', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const blockEl = el.closest('.pc-block');
                const blockId = blockEl ? blockEl.dataset.blockId : null;
                if (!blockId) return;
                renameBlockLabel(blockId);
            });
        });

        // Token remove buttons
        container.querySelectorAll('.pc-token-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const blockId = e.target.dataset.blockId;
                const tokenIdx = parseInt(e.target.dataset.tokenIdx);
                removeToken(blockId, tokenIdx);
            });
        });

        // Block-level clear buttons (clear tokens only inside the block)
        container.querySelectorAll('.pc-block-clear').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const blockId = e.currentTarget.dataset.blockId;
                clearBlockTokens(blockId);
            });
        });

        // Block delete buttons (remove the whole block)
        container.querySelectorAll('.pc-block-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const blockId = e.currentTarget.dataset.blockId;
                deleteBlock(blockId);
            });
        });

        // Token click (selection for multi-move)
        container.querySelectorAll('.pc-token').forEach(el => {
            el.addEventListener('click', (e) => {
                // ignore clicks on remove button
                if (e.target && e.target.classList && e.target.classList.contains('pc-token-remove')) {
                    return;
                }
                const id = el.dataset.tokenId;
                if (!id) return;

                const isMulti = e.ctrlKey || e.metaKey;
                if (!isMulti) {
                    // single select
                    clearTokenSelection();
                    selectedTokenIds.add(id);
                } else {
                    // toggle
                    if (selectedTokenIds.has(id)) {
                        selectedTokenIds.delete(id);
                    } else {
                        selectedTokenIds.add(id);
                    }
                }
                applyTokenSelectionClasses();
            });
        });

        // Token double click: temporary hide/unhide (excluded from final prompt)
        container.querySelectorAll('.pc-token').forEach(el => {
            el.addEventListener('dblclick', (e) => {
                if (e.target && e.target.classList && e.target.classList.contains('pc-token-remove')) {
                    return;
                }
                e.preventDefault();
                e.stopPropagation();
                const blockId = el.dataset.blockId;
                const tokenIdx = parseInt(el.dataset.tokenIdx, 10);
                toggleTokenHidden(blockId, tokenIdx);
            });
        });

        // Token drag-and-drop reorder (within the same block)
        container.querySelectorAll('.pc-token[draggable="true"]').forEach(el => {
            el.addEventListener('dragstart', onTokenDragStart);
            el.addEventListener('dragover', onTokenDragOver);
            el.addEventListener('drop', onTokenDrop);
            el.addEventListener('dragend', onTokenDragEnd);
        });

        // Token input fields
        container.querySelectorAll('.pc-token-input').forEach(input => {
            input.addEventListener('keydown', (e) => {
                // If local tag suggestion is handling Enter, skip default add-from-input
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
            // Remember last-focused block for tag dictionary insertion
            input.addEventListener('focus', (e) => {
                const blockId = e.target.dataset.blockId;
                if (blockId) {
                    window.PromptComposerActiveBlockId = blockId;
                }
            });

            // Integrate with a1111-sd-webui-tagcomplete if available
            try {
                if (typeof window.addAutocompleteToArea === 'function') {
                    window.addAutocompleteToArea(input);
                } else if (typeof addAutocompleteToArea === 'function') {
                    addAutocompleteToArea(input);
                }
            } catch (e) {
                // ignore if tagcomplete is not loaded
            }

            // Local lightweight tag suggestions (danbooru.csv)
            setupLocalTagSuggest(input);
        });

        // Special token buttons (BREAK / AND) were moved to Tag Dictionary quickbar.

        // Drag and drop
        container.querySelectorAll('.pc-block[draggable="true"]').forEach(el => {
            el.addEventListener('dragstart', onDragStart);
            el.addEventListener('dragover', onDragOver);
            el.addEventListener('dragend', onDragEnd);
            el.addEventListener('drop', onDrop);
        });
    }

    function onTokenDragStart(e) {
        const tokenEl = e.target.closest('.pc-token');
        if (!tokenEl) return;
        // ブロック全体のドラッグ開始に伝播させない
        e.stopPropagation();
        // ignore drags started from the remove button
        if (e.target && e.target.classList && e.target.classList.contains('pc-token-remove')) return;

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
        if (tokenEl) {
            if (tokenEl.dataset.blockId !== fromId) return; // 同一ブロック内のみ並べ替え
            tokenEl.classList.add('pc-token-drop-target');
        } else if (listEl) {
            const blockEl = listEl.closest('.pc-block');
            if (!blockEl || blockEl.dataset.blockId !== fromId) return;
            listEl.classList.add('pc-token-drop-target');
        }
    }

    function onTokenDrop(e) {
        const tokenEl = e.target.closest('.pc-token');
        const listEl = e.target.closest('.pc-token-list');
        if (!draggedToken || (!tokenEl && !listEl)) return;
        e.stopPropagation();
        e.preventDefault();

        // 決定するブロックIDと挿入位置
        let blockId = null;
        let toIdx = 0;

        if (tokenEl) {
            blockId = tokenEl.dataset.blockId;
            toIdx = parseInt(tokenEl.dataset.tokenIdx);
            if (Number.isNaN(toIdx)) toIdx = 0;
        } else if (listEl) {
            const blockEl = listEl.closest('.pc-block');
            if (!blockEl) return;
            blockId = blockEl.dataset.blockId;
            toIdx = listEl.children.length; // 末尾
        }

        if (!blockId || blockId !== draggedToken.fromBlockId) return; // ブロックをまたいだドラッグは無効

        const tokenIds = draggedToken.tokenIds || [];
        if (!tokenIds.length) return;
        const allBlocks = [...blocks, ...negativeBlocks];

        // Collect and remove tokens only from the source block
        const sourceBlock = allBlocks.find(b => b.id === draggedToken.fromBlockId);
        if (!sourceBlock) return;
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

        const targetBlock = allBlocks.find(b => b.id === blockId);
        if (!targetBlock) return;

        // Compute insertion index after removals
        let insertIdx = toIdx;
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

    function addToken(blockId, label, text, options = {}) {
        const block = findBlock(blockId);
        if (!block) return;

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
        renderBlocks();
    }

    function addTokenFromInput(blockId, rawText) {
        // If contains separators, split into multiple tokens
        if (/[,\n、]/.test(rawText)) {
            rawText
                .split(/[,\n、]/)
                .map(t => t.trim())
                .filter(t => t.length > 0)
                .forEach(part => addTokenFromInput(blockId, part));
            return;
        }

        // Async: normalize spaces -> underscores and fetch JP translation
        (async () => {
            const normSpaces = (s) => (s || '').trim().replace(/\s+/g, '_');

            // Parse weight syntax: (tag:1.2) or tag
            let innerText = rawText;
            let weight = null;
            let emittedText = rawText;

            const weightMatch = rawText.match(/^\((.+):([0-9.]+)\)$/);
            if (weightMatch) {
                innerText = weightMatch[1];
                weight = parseFloat(weightMatch[2]);
                const norm = normSpaces(innerText);
                emittedText = `(${norm}:${weightMatch[2]})`;
                innerText = norm;
            } else {
                innerText = normSpaces(innerText);
                emittedText = innerText;
            }

            let jp = '';
            try {
                const resp = await fetch(`/prompt-composer/api/tag-translate?tag=${encodeURIComponent(innerText)}`);
                if (resp.ok) {
                    const data = await resp.json();
                    jp = (data && data.jp) ? String(data.jp) : '';
                }
            } catch (_) {}

            addToken(blockId, innerText, emittedText, {
                weight: weight,
                sourceType: 'manual',
                isTrigger: false,
                jp: jp || null
            });
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

        // Set profile dropdown value
        const profileSelect = document.getElementById('pc_order_profile');
        if (profileSelect) {
            const selectEl = profileSelect.querySelector('select') || profileSelect.querySelector('input');
            if (selectEl) {
                selectEl.value = currentOrderProfile;
                selectEl.dispatchEvent(new Event('change', { bubbles: true }));
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

        addToken(targetBlock.id, label, text, {
            weight: asset.defaultWeight,
            sourceType: asset.type,
            isTrigger: false,
            previewUrl: asset.previewUrl || null
        });

        // Embeddings: insert only the token (filename). Do not auto-add trigger words.
        if (asset.type === 'embedding') {
            return;
        }

        // LoRA: also add trigger words to appropriate block (optional convenience)
        if (asset.triggerWords && asset.triggerWords.length > 0) {
            // Determine where trigger words go
            let triggerBlock = blocks.find(b => b.type === 'lora')
                || blocks.find(b => b.type === 'embedding')
                || targetBlock;
            
            asset.triggerWords.forEach(tw => {
                if (!triggerBlock.tokens.some(t => t.text === tw)) {
                    addToken(triggerBlock.id, tw, tw, {
                        sourceType: asset.type,
                        isTrigger: true
                    });
                }
            });
        }
    }

    // ===== Drag and Drop =====
    function onDragStart(e) {
        draggedBlock = e.target.closest('.pc-block');
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
            orderProfile: currentOrderProfile
        };
    }

    function loadState(state) {
        if (!state) return;

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
            try { backfillMissingJp(); } catch (_) {}
        }, 50);

        renderBlocks();
    }

    async function backfillMissingJp() {
        const allBlocks = [...blocks, ...negativeBlocks];
        const missing = [];
        allBlocks.forEach(b => {
            (b.tokens || []).forEach(t => {
                if (t && !t.jp && t.text && typeof t.text === 'string') {
                    // Skip obvious non-tags
                    const s = t.text.trim();
                    if (!s) return;
                    if (s === 'BREAK' || s === 'AND') return;
                    if (s.startsWith('__') && s.endsWith('__')) return;
                    missing.push(t);
                }
            });
        });

        // Avoid spamming network: translate only a handful per restore
        const limit = 40;
        for (const t of missing.slice(0, limit)) {
            const tag = String(t.text || '').trim();
            try {
                const resp = await fetch(`/prompt-composer/api/tag-translate?tag=${encodeURIComponent(tag)}`);
                if (!resp.ok) continue;
                const data = await resp.json();
                const jp = (data && data.jp) ? String(data.jp).trim() : '';
                if (jp) t.jp = jp;
            } catch (_) {
                // ignore
            }
        }
        // re-render once if we updated something
        if (missing.length) renderBlocks();
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

    function generateId() {
        return Math.random().toString(36).substr(2, 9);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function setGradioValue(elemId, value) {
        const container = document.getElementById(elemId);
        if (!container) return;
        
        const textarea = container.querySelector('textarea');
        if (textarea) {
            textarea.value = value;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        }
        checkWarnings();
    }

    // ===== Public API =====
    window.PromptComposer = {
        init,
        insertAsset,
        getState,
        loadState,
        addToken,
        renderBlocks,
        sortBlocksByProfile,
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
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

})();
