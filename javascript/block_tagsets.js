/**
 * Per-block named presets (新規保存 / 読込 / 上書き / 削除).
 */
(function() {
    'use strict';

    const BLOCK_TYPES = new Set([
        'quality', 'character', 'subject', 'appearance', 'outfit', 'expression',
        'composition', 'background', 'lighting', 'style', 'lora', 'embedding', 'negative'
    ]);

    let collectionsCache = [];
    let cacheTime = 0;
    const CACHE_MS = 5000;
    /** @type {Record<string, { collectionId: string, name: string }>} */
    const selectionState = {};
    /** @type {Set<string> | null} */
    let embeddingNamesCache = null;
    let embeddingNamesLoading = null;

    function normalizeBlockType(blockType) {
        const t = (blockType || '').trim();
        if (BLOCK_TYPES.has(t)) return t;
        // Order-profile custom column ids (e.g. ________) — group with same normalized key
        if (t && /^_+$/.test(t)) return t;
        return 'character';
    }

    function normalizeBlockLabel(label) {
        return String(label || '').trim();
    }

    /** Saved sets visible in this column (match display name memo and/or block type). */
    function collectionsForBar(blockOrType, optLabel) {
        let blockType;
        let label = '';
        if (blockOrType && typeof blockOrType === 'object') {
            blockType = blockOrType.type;
            label = normalizeBlockLabel(blockOrType.label);
        } else {
            blockType = blockOrType;
            label = normalizeBlockLabel(optLabel);
        }
        const norm = normalizeBlockType(blockType);
        return collectionsCache.filter(c => {
            const cMemo = normalizeBlockLabel(c.memo);
            const cNorm = normalizeBlockType(c.block);
            if (label && cMemo && cMemo === label) return true;
            if (cNorm !== norm) return false;
            if (cMemo && label && cMemo !== label) return false;
            return true;
        });
    }

    function showTagsetMessage(message) {
        alert(message);
    }

    function findBlock(blockId) {
        const PC = window.PromptComposer;
        if (!PC) return null;
        return (PC.blocks || []).concat(PC.negativeBlocks || []).find(b => b.id === blockId) || null;
    }

    function getBar(blockId) {
        return document.querySelector(`.pc-block-tagset-bar[data-block-id="${CSS.escape(blockId)}"]`);
    }

    function getNameInput(blockId) {
        const bar = getBar(blockId);
        return bar ? bar.querySelector('.pc-block-tagset-name') : null;
    }

    function getSelect(blockId) {
        const bar = getBar(blockId);
        return bar ? bar.querySelector('.pc-block-tagset-select') : null;
    }

    function getEnteredName(blockId) {
        const input = getNameInput(blockId);
        return input ? input.value.trim() : '';
    }

    function tokensToTags(tokens) {
        return (tokens || []).map(tok => {
            const t = String(tok.text || '').trim();
            if (!t) return null;
            const l = String(tok.label || t).trim() || t;
            const tag = { l, t, cat: '' };
            const jp = String(tok.jp || '').trim();
            if (jp && jp !== l && jp !== t) {
                tag.j = jp;
            }
            const src = String(tok.sourceType || '').trim();
            if (src === 'lora' || src === 'embedding') {
                tag.src = src;
            } else if (src && src !== 'manual' && src !== 'tagset') {
                tag.src = src;
            }
            if (typeof tok.weight === 'number' && !Number.isNaN(tok.weight) && tok.weight !== 1) {
                tag.w = tok.weight;
            }
            if (tok.isTrigger === true) {
                tag.tw = 1;
            }
            if (tok.hidden === true) {
                tag.hid = 1;
            }
            return tag;
        }).filter(Boolean);
    }

    function normalizeAssetKey(name) {
        return String(name || '')
            .trim()
            .toLowerCase()
            .replace(/\.(pt|safetensors|ckpt|bin)$/i, '');
    }

    async function ensureEmbeddingNamesCache() {
        if (embeddingNamesCache) return embeddingNamesCache;
        if (embeddingNamesLoading) return embeddingNamesLoading;
        embeddingNamesLoading = (async () => {
            const set = new Set();
            try {
                const resp = await fetch('/prompt-composer/api/assets?type=embedding&limit=20000');
                if (resp.ok) {
                    const data = await resp.json();
                    (data.assets || []).forEach(asset => {
                        [asset.name, asset.displayName, asset.insertTemplate].forEach(v => {
                            const key = normalizeAssetKey(v);
                            if (key) set.add(key);
                        });
                    });
                }
            } catch (err) {
                console.warn('[Prompt Composer] Embedding index for presets:', err);
            }
            embeddingNamesCache = set;
            embeddingNamesLoading = null;
            return set;
        })();
        return embeddingNamesLoading;
    }

    function isKnownEmbeddingName(text, label, embSet) {
        if (!embSet || !embSet.size) return false;
        const candidates = [text, label];
        const parsed = parseWeightedText(text);
        if (parsed && parsed.label) candidates.push(parsed.label);
        for (const raw of candidates) {
            const key = normalizeAssetKey(raw);
            if (key && embSet.has(key)) return true;
        }
        return false;
    }

    function inferSourceType(text, label, embSet) {
        const t = String(text || '').trim();
        if (!t) return 'manual';
        if (/^<lora:/i.test(t)) return 'lora';
        if (t.startsWith('__') && t.endsWith('__')) return 'embedding';
        if (isKnownEmbeddingName(t, label, embSet)) return 'embedding';
        return 'manual';
    }

    function parseWeightedText(text) {
        const m = String(text || '').trim().match(/^\((.+):(-?[0-9.]+)\)$/);
        if (!m) return null;
        const weight = parseFloat(m[2]);
        if (!Number.isFinite(weight)) return null;
        return { label: m[1].trim(), weight };
    }

    function tagsToTokens(tags, embSet) {
        return (tags || []).map(tag => {
            const text = String(tag.t || tag.text || '').trim();
            if (!text) return null;

            let label = String(tag.l || tag.label || text).trim() || text;
            let weight = tag.w != null ? Number(tag.w) : (tag.weight != null ? Number(tag.weight) : null);
            if (!Number.isFinite(weight)) weight = null;

            const parsedWeight = weight == null ? parseWeightedText(text) : null;
            if (parsedWeight) {
                if (!tag.l && !tag.label) label = parsedWeight.label;
                weight = parsedWeight.weight;
            }

            let sourceType = String(tag.src || tag.sourceType || '').trim() || inferSourceType(text, label, embSet);
            const isTrigger = tag.tw === 1 || tag.tw === true || tag.isTrigger === true;
            const hidden = tag.hid === 1 || tag.hid === true || tag.hidden === true;
            const jpRaw = String(tag.j || tag.jp || '').trim();
            const jp = jpRaw && jpRaw !== label && jpRaw !== text ? jpRaw : null;

            return {
                label,
                text,
                jp,
                sourceType,
                weight,
                isTrigger,
                hidden
            };
        }).filter(Boolean);
    }

    async function fetchCollections(force) {
        const now = Date.now();
        if (!force && collectionsCache.length && now - cacheTime < CACHE_MS) {
            return collectionsCache;
        }
        const resp = await fetch('/prompt-composer/api/ips/collections');
        if (!resp.ok) {
            throw new Error('一覧の取得に失敗しました (HTTP ' + resp.status + ')');
        }
        const data = await resp.json();
        collectionsCache = data.collections || [];
        cacheTime = now;
        return collectionsCache;
    }

    function findCollectionByName(blockOrType, name) {
        const n = (name || '').trim();
        if (!n) return null;
        return collectionsForBar(blockOrType).find(c => c.name === n) || null;
    }

    function setSelection(blockId, collectionId) {
        if (!collectionId) {
            delete selectionState[blockId];
            return;
        }
        const col = collectionsCache.find(c => c.id === collectionId);
        if (col) {
            selectionState[blockId] = { collectionId: col.id, name: col.name };
        }
    }

    function syncSelectToName(blockId) {
        const sel = getSelect(blockId);
        const name = getEnteredName(blockId);
        if (!sel) return;
        if (!name) {
            sel.value = '';
            delete selectionState[blockId];
            return;
        }
        const block = findBlock(blockId);
        if (!block) return;
        const hit = findCollectionByName(block, name);
        if (hit) {
            sel.value = hit.id;
            setSelection(blockId, hit.id);
        } else {
            sel.value = '';
            delete selectionState[blockId];
        }
    }

    function onSelectChange(blockId) {
        const sel = getSelect(blockId);
        const input = getNameInput(blockId);
        if (!sel || !input) return;
        const id = sel.value;
        if (!id) {
            delete selectionState[blockId];
            return;
        }
        const col = collectionsCache.find(c => c.id === id);
        if (col) {
            input.value = col.name;
            setSelection(blockId, id);
        }
    }

    function restoreBarSelection(blockId, sel, nameInput, list, blockType, preserve) {
        const st = selectionState[blockId];
        const prevSel = (preserve && preserve.selId) || '';
        const prevName = (preserve && preserve.name) || '';
        let restoreId = (st && st.collectionId) || prevSel || '';
        if (!restoreId && prevName && blockId) {
            const block = findBlock(blockId);
            const hit = block ? findCollectionByName(block, prevName) : null;
            restoreId = hit ? hit.id : '';
        }
        if (restoreId && list.some(c => c.id === restoreId)) {
            sel.value = restoreId;
            const col = list.find(c => c.id === restoreId);
            if (nameInput && col) {
                nameInput.value = col.name;
            }
            setSelection(blockId, restoreId);
            return;
        }
        if (nameInput && prevName) {
            nameInput.value = prevName;
            syncSelectToName(blockId);
        }
    }

    function populateTagsetSelect(sel, list, blockId, nameInput, blockType, preserve) {
        if (!sel) return;
        sel.innerHTML = '<option value="">保存済み</option>';
        list.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            opt.title = `${c.tagCount} 件`;
            sel.appendChild(opt);
        });
        restoreBarSelection(blockId, sel, nameInput, list, blockType, preserve);
    }

    function populateBarFromBlock(bar, forceList) {
        const blockId = bar.dataset.blockId;
        const sel = bar.querySelector('.pc-block-tagset-select');
        const nameInput = bar.querySelector('.pc-block-tagset-name');
        if (!sel || !blockId) return;
        const block = findBlock(blockId);
        const list = forceList || (block ? collectionsForBar(block) : collectionsForBar(bar.dataset.blockType));
        const preserve = {
            selId: sel.value,
            name: nameInput ? nameInput.value.trim() : ''
        };
        populateTagsetSelect(sel, list, blockId, nameInput, block ? block.type : bar.dataset.blockType, preserve);
    }

    function refreshBarsForBlockType(blockType, forceFetch) {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return Promise.resolve();
        const norm = normalizeBlockType(blockType);
        const run = async () => {
            if (forceFetch) await fetchCollections(true);
            else if (!collectionsCache.length) await fetchCollections(false);
            container.querySelectorAll('.pc-block-tagset-bar').forEach(bar => {
                if (normalizeBlockType(bar.dataset.blockType) !== norm) return;
                populateBarFromBlock(bar);
            });
        };
        return run();
    }

    async function refreshAllBlockTagSetBars() {
        const container = document.getElementById('pc_blocks_container');
        if (!container) return;
        await fetchCollections(false);

        container.querySelectorAll('.pc-block-tagset-bar').forEach(bar => {
            populateBarFromBlock(bar);
        });
    }

    function resolveCollectionId(blockId) {
        const sel = getSelect(blockId);
        if (sel && sel.value) return sel.value;
        const block = findBlock(blockId);
        if (!block) return '';
        const name = getEnteredName(blockId);
        const hit = findCollectionByName(block, name);
        return hit ? hit.id : '';
    }

    async function persistBlockTagSet(blockId, overwriteId) {
        const block = findBlock(blockId);
        if (!block) {
            showTagsetMessage('ブロックが見つかりません。ページを再読み込みしてください。');
            return false;
        }
        const name = getEnteredName(blockId);
        if (!name) {
            showTagsetMessage('保存名を入力してください');
            getNameInput(blockId)?.focus();
            return false;
        }
        const tags = tokensToTags(block.tokens);
        if (!tags.length) {
            showTagsetMessage('保存するタグがありません');
            return false;
        }

        const blockKey = normalizeBlockType(block.type);
        const existing = findCollectionByName(block, name);
        if (!overwriteId && existing) {
            showTagsetMessage(`「${name}」は既にあります。\n上書きボタン（↻）を使うか、別の名前で新規保存してください。`);
            return false;
        }
        if (overwriteId && !collectionsCache.some(c => c.id === overwriteId)) {
            showTagsetMessage('上書きする保存を選択してください');
            return false;
        }

        const payload = {
            id: overwriteId || undefined,
            name,
            block: (block.type || blockKey).trim(),
            memo: block.label || '',
            tags
        };

        let resp;
        try {
            resp = await fetch('/prompt-composer/api/ips/collections', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } catch (err) {
            console.warn('[Prompt Composer] Preset save network error:', err);
            showTagsetMessage('保存に失敗しました（サーバーに接続できません）');
            return false;
        }

        if (!resp.ok) {
            let detail = '';
            try {
                const err = await resp.json();
                detail = err.error || err.detail || '';
            } catch (_) { /* ignore */ }
            showTagsetMessage('保存に失敗しました' + (detail ? '：' + detail : ' (HTTP ' + resp.status + ')'));
            return false;
        }

        const saved = await resp.json();
        collectionsCache = collectionsCache.filter(c => c.id !== saved.id);
        collectionsCache.push({
            id: saved.id,
            name: saved.name || name,
            block: saved.block || blockKey,
            memo: saved.memo || '',
            tagCount: saved.tagCount != null ? saved.tagCount : tags.length,
            createdAt: saved.createdAt || '',
            updatedAt: saved.updatedAt || ''
        });
        cacheTime = Date.now();
        await refreshAllBlockTagSetBars();
        const sel = getSelect(blockId);
        const input = getNameInput(blockId);
        if (input) input.value = saved.name || name;
        if (sel) sel.value = saved.id;
        setSelection(blockId, saved.id);

        const verb = overwriteId ? '更新' : '保存';
        showTagsetMessage(`「${saved.name || name}」を${verb}しました`);
        return true;
    }

    async function saveNewBlockTagSet(blockId) {
        return persistBlockTagSet(blockId, null);
    }

    async function overwriteBlockTagSet(blockId) {
        const collectionId = resolveCollectionId(blockId);
        if (!collectionId) {
            showTagsetMessage('上書きする保存をプルダウンで選ぶか、保存名を入力してください');
            return false;
        }
        const name = getEnteredName(blockId) || collectionsCache.find(c => c.id === collectionId)?.name;
        if (!confirm(`「${name}」を現在のタグで上書きしますか？`)) return false;
        return persistBlockTagSet(blockId, collectionId);
    }

    async function loadBlockTagSet(blockId, append) {
        const collectionId = resolveCollectionId(blockId);
        const block = findBlock(blockId);
        if (!block || !collectionId) {
            showTagsetMessage('保存済みから選ぶか、保存名を入力してください');
            return false;
        }
        const resp = await fetch('/prompt-composer/api/ips/collections/' + encodeURIComponent(collectionId));
        if (!resp.ok) {
            showTagsetMessage('読み込みに失敗しました');
            return false;
        }
        const col = await resp.json();
        const tags = col.tags || [];
        if (!tags.length) {
            showTagsetMessage('保存内容が空です');
            return false;
        }
        const input = getNameInput(blockId);
        const sel = getSelect(blockId);
        if (input) input.value = col.name || '';
        if (sel) sel.value = collectionId;
        setSelection(blockId, collectionId);

        const mode = append ? 'append' : 'replace';
        if (block.tokens.length) {
            const msg = mode === 'append'
                ? '現在のタグに追加しますか？'
                : '現在のタグを置き換えますか？';
            if (!confirm(msg)) return false;
        }

        const PC = window.PromptComposer;
        if (!PC) return false;

        if (mode !== 'append' && PC.clearBlockTokensSilent) {
            PC.clearBlockTokensSilent(blockId);
        } else if (mode !== 'append') {
            block.tokens = [];
        }

        const embSet = await ensureEmbeddingNamesCache();
        const specs = tagsToTokens(tags, embSet).map(tok => ({
            label: tok.label,
            text: tok.text,
            sourceType: tok.sourceType,
            jp: tok.jp,
            weight: tok.weight,
            isTrigger: tok.isTrigger,
            hidden: tok.hidden
        }));
        if (PC.addTokensBulk) {
            PC.addTokensBulk(blockId, specs, { scheduleJpBackfill: true, jpBackfillDelay: 250 });
        } else {
            specs.forEach(tok => {
                PC.addToken(blockId, tok.label, tok.text, {
                    sourceType: tok.sourceType,
                    jp: tok.jp,
                    weight: tok.weight,
                    isTrigger: tok.isTrigger
                });
            });
        }
        return true;
    }

    async function deleteBlockTagSet(blockId) {
        const collectionId = resolveCollectionId(blockId);
        const name = getEnteredName(blockId) || (collectionsCache.find(c => c.id === collectionId)?.name);
        if (!collectionId) {
            showTagsetMessage('削除する保存を選ぶか、保存名を入力してください');
            return false;
        }
        if (!confirm(`「${name || 'この保存'}」を削除しますか？`)) return false;

        const resp = await fetch('/prompt-composer/api/ips/collections/' + encodeURIComponent(collectionId), {
            method: 'DELETE'
        });
        if (!resp.ok) {
            showTagsetMessage('削除に失敗しました');
            return false;
        }
        const input = getNameInput(blockId);
        const sel = getSelect(blockId);
        if (input) input.value = '';
        if (sel) sel.value = '';
        delete selectionState[blockId];
        const block = findBlock(blockId);
        const blockKey = block ? normalizeBlockType(block.type) : '';
        collectionsCache = collectionsCache.filter(c => c.id !== collectionId);
        cacheTime = Date.now();
        await refreshAllBlockTagSetBars();
        showTagsetMessage(`「${name || '保存'}」を削除しました`);
        return true;
    }

    window.PromptComposerBlockTagsets = {
        refreshAllBlockTagSetBars,
        refreshBarsForBlockType,
        saveNew: saveNewBlockTagSet,
        load: loadBlockTagSet,
        overwrite: overwriteBlockTagSet,
        delete: deleteBlockTagSet,
        onSelectChange,
        onNameInput: syncSelectToName
    };

    function init() {
        if (!window.PromptComposer) {
            setTimeout(init, 400);
            return;
        }
        ensureEmbeddingNamesCache().catch(() => {});
        refreshAllBlockTagSetBars().catch(err => {
            console.warn('[Prompt Composer] Presets refresh failed:', err);
        });
        console.log('[Prompt Composer] Block presets initialized');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1200));
    } else {
        setTimeout(init, 1200);
    }
    if (typeof onUiLoaded === 'function') {
        onUiLoaded(() => setTimeout(init, 1200));
    }
})();
