/**
 * Per-block named presets (新規保存 / 読込 / 上書き / 削除).
 */
(function() {
    'use strict';

    const BLOCK_TYPES = new Set([
        'quality', 'character', 'subject', 'appearance', 'outfit', 'expression',
        'composition', 'background', 'lighting', 'style', 'lora', 'embedding', 'negative'
    ]);

    const BLOCK_TYPE_LABELS = {
        quality: '🏆 品質',
        subject: '🎯 主題',
        character: '👤 キャラ',
        appearance: '✨ 外見',
        outfit: '👗 衣装',
        expression: '😊 表情',
        composition: '📐 構図',
        background: '🌄 背景',
        lighting: '💡 光',
        style: '🎨 画風',
        lora: '🔧 LoRA',
        embedding: '📦 Embedding',
        negative: '🚫 Negative'
    };

    let collectionsCache = [];
    let cacheTime = 0;
    const CACHE_MS = 5000;
    /** @type {Record<string, { collectionId: string, name: string }>} */
    const selectionState = {};
    /** @type {Set<string> | null} */
    let embeddingNamesCache = null;
    let embeddingNamesLoading = null;
    let pickUiBound = false;

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document;
    }

    function blocksContainer() {
        const byDoc = document.getElementById('pc_blocks_container');
        if (byDoc) return byDoc;
        try {
            const root = appRoot();
            if (root && typeof root.getElementById === 'function') {
                const byRoot = root.getElementById('pc_blocks_container');
                if (byRoot) return byRoot;
            }
            if (root && root.querySelector) {
                return root.querySelector('#pc_blocks_container');
            }
        } catch (_) { /* ignore */ }
        return null;
    }

    function queryAllBars(selector) {
        const seen = new Set();
        const out = [];
        const add = (nodeList) => {
            nodeList.forEach((el) => {
                if (!seen.has(el)) {
                    seen.add(el);
                    out.push(el);
                }
            });
        };
        add(document.querySelectorAll(selector));
        try {
            const root = appRoot();
            if (root && root !== document && root.querySelectorAll) {
                add(root.querySelectorAll(selector));
            }
        } catch (_) { /* ignore */ }
        return out;
    }

    function normalizeBlockType(blockType) {
        const t = (blockType || '').trim();
        if (!t) return 'character';
        if (BLOCK_TYPES.has(t)) return t;
        if (/^_+$/.test(t)) return t;
        return t;
    }

    function blockTypeLabel(blockType) {
        const norm = normalizeBlockType(blockType);
        return BLOCK_TYPE_LABELS[norm] || norm || 'その他';
    }

    function normalizeBlockLabel(label) {
        return String(label || '').trim();
    }

    /** Saved sets for this column only (match display label / memo; legacy rows may match block type). */
    function collectionsForBar(blockOrType) {
        let blockType = '';
        let label = '';
        if (blockOrType && typeof blockOrType === 'object') {
            blockType = blockOrType.type;
            label = normalizeBlockLabel(blockOrType.label);
        } else {
            blockType = blockOrType;
        }
        const norm = normalizeBlockType(blockType);
        const normLabel = normalizeBlockLabel(label);
        return collectionsCache.filter((c) => {
            const cMemo = normalizeBlockLabel(c.memo);
            const cBlock = normalizeBlockType(c.block);
            if (normLabel) {
                if (cMemo && cMemo === normLabel) return true;
                if (!cMemo && cBlock === norm) return true;
                return false;
            }
            return cBlock === norm;
        }).sort((left, right) => String(right.updatedAt || '').localeCompare(String(left.updatedAt || '')));
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
        const sel = `.pc-block-tagset-bar[data-block-id="${CSS.escape(blockId)}"]`;
        return document.querySelector(sel) || appRoot().querySelector(sel);
    }

    function getNameInput(blockId) {
        const bar = getBar(blockId);
        return bar ? bar.querySelector('.pc-block-tagset-name') : null;
    }

    function getPickWrap(blockId) {
        const bar = getBar(blockId);
        return bar ? bar.querySelector('.pc-block-tagset-pick') : null;
    }

    function getPickButton(blockId) {
        const wrap = getPickWrap(blockId);
        return wrap ? wrap.querySelector('.pc-block-tagset-pick-btn') : null;
    }

    function getPickMenu(blockId) {
        const wrap = getPickWrap(blockId);
        return wrap ? wrap.querySelector('.pc-block-tagset-pick-menu') : null;
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
        let blockType = blockOrType;
        let label = '';
        if (blockOrType && typeof blockOrType === 'object') {
            blockType = blockOrType.type;
            label = normalizeBlockLabel(blockOrType.label);
        }
        const norm = normalizeBlockType(blockType);
        const normLabel = normalizeBlockLabel(label);
        const matches = collectionsCache.filter(c => c.name === n);
        if (!matches.length) return null;
        if (normLabel) {
            return matches.find(c => normalizeBlockLabel(c.memo) === normLabel)
                || matches.find(c => normalizeBlockType(c.block) === norm)
                || matches[0];
        }
        return matches.find(c => normalizeBlockType(c.block) === norm) || matches[0];
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

    function formatPickLabel(col, block) {
        const memo = normalizeBlockLabel(col.memo);
        const currentLabel = block ? normalizeBlockLabel(block.label) : '';
        const name = col.name || '';
        if (currentLabel && memo === currentLabel) {
            return name;
        }
        if (memo) {
            return `${name} (${memo})`;
        }
        return `[${blockTypeLabel(col.block)}] ${name}`;
    }

    function setPickSelection(blockId, collectionId) {
        const btn = getPickButton(blockId);
        const menu = getPickMenu(blockId);
        if (!collectionId) {
            setSelection(blockId, '');
            if (btn) btn.textContent = '保存済み';
            if (menu) {
                menu.querySelectorAll('.pc-block-tagset-pick-item').forEach((el) => {
                    el.classList.toggle('is-selected', false);
                });
            }
            return;
        }
        const col = collectionsCache.find(c => c.id === collectionId);
        if (!col) return;
        setSelection(blockId, collectionId);
        const block = findBlock(blockId);
        if (btn) btn.textContent = formatPickLabel(col, block);
        if (menu) {
            menu.querySelectorAll('.pc-block-tagset-pick-item').forEach((el) => {
                el.classList.toggle('is-selected', el.dataset.collectionId === collectionId);
            });
        }
    }

    function syncSelectToName(blockId) {
        const name = getEnteredName(blockId);
        if (!name) {
            setPickSelection(blockId, '');
            return;
        }
        const block = findBlock(blockId);
        if (!block) return;
        const hit = findCollectionByName(block, name);
        if (hit) {
            setPickSelection(blockId, hit.id);
        } else {
            setPickSelection(blockId, '');
        }
    }

    function onSelectChange(blockId, collectionId) {
        const input = getNameInput(blockId);
        const id = collectionId || '';
        if (!id) {
            delete selectionState[blockId];
            setPickSelection(blockId, '');
            return;
        }
        const col = collectionsCache.find(c => c.id === id);
        if (col) {
            if (input) input.value = col.name;
            setPickSelection(blockId, id);
        }
    }

    function restorePickSelection(blockId, nameInput, list, preserve) {
        const st = selectionState[blockId];
        const prevId = (preserve && preserve.selId) || (st && st.collectionId) || '';
        const prevName = (preserve && preserve.name) || '';
        let restoreId = prevId;
        if (!restoreId && prevName && blockId) {
            const block = findBlock(blockId);
            const hit = block ? findCollectionByName(block, prevName) : null;
            restoreId = hit ? hit.id : '';
        }
        if (restoreId && list.some(c => c.id === restoreId)) {
            const col = list.find(c => c.id === restoreId);
            if (nameInput && col) nameInput.value = col.name;
            setPickSelection(blockId, restoreId);
            return;
        }
        if (nameInput && prevName) {
            nameInput.value = prevName;
            syncSelectToName(blockId);
            return;
        }
        setPickSelection(blockId, '');
    }

    function populateTagsetPick(menu, list, blockId, nameInput, preserve) {
        if (!menu) return;
        const block = blockId ? findBlock(blockId) : null;
        menu.innerHTML = '';
        if (!list.length) {
            const empty = document.createElement('div');
            empty.className = 'pc-block-tagset-pick-empty';
            empty.textContent = '保存がありません';
            menu.appendChild(empty);
        } else {
            list.forEach((c) => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'pc-block-tagset-pick-item';
                item.dataset.collectionId = c.id;
                item.dataset.blockId = blockId;
                item.textContent = formatPickLabel(c, block);
                item.title = `${c.tagCount || 0} 件`;
                menu.appendChild(item);
            });
        }
        restorePickSelection(blockId, nameInput, list, preserve);
    }

    function populateBarFromBlock(bar, forceList) {
        const blockId = bar.dataset.blockId;
        const menu = bar.querySelector('.pc-block-tagset-pick-menu');
        const nameInput = bar.querySelector('.pc-block-tagset-name');
        const btn = bar.querySelector('.pc-block-tagset-pick-btn');
        if (!menu || !blockId) return;
        const block = findBlock(blockId);
        const list = forceList || (block ? collectionsForBar(block) : collectionsForBar(bar.dataset.blockType));
        const preserve = {
            selId: selectionState[blockId]?.collectionId || '',
            name: nameInput ? nameInput.value.trim() : ''
        };
        populateTagsetPick(menu, list, blockId, nameInput, preserve);
        if (btn && !selectionState[blockId]?.collectionId) {
            btn.textContent = list.length ? `保存済み (${list.length})` : '保存済み';
        }
    }

    function positionPickMenu(blockId) {
        const menu = getPickMenu(blockId);
        const btn = getPickButton(blockId);
        if (!menu || !btn) return;
        const rect = btn.getBoundingClientRect();
        const maxH = Math.min(window.innerHeight * 0.46, 320);
        menu.style.position = 'fixed';
        menu.style.left = `${Math.max(8, rect.left)}px`;
        menu.style.top = `${rect.bottom + 4}px`;
        menu.style.width = `${Math.max(rect.width, 180)}px`;
        menu.style.right = 'auto';
        menu.style.maxHeight = `${maxH}px`;
        menu.style.zIndex = '1200';
    }

    function resetPickMenuPosition(menu) {
        if (!menu) return;
        menu.style.position = '';
        menu.style.left = '';
        menu.style.top = '';
        menu.style.width = '';
        menu.style.right = '';
        menu.style.maxHeight = '';
        menu.style.zIndex = '';
    }

    function closeAllPickMenus(exceptBlockId) {
        queryAllBars('.pc-block-tagset-pick-menu').forEach((menu) => {
            const bid = menu.dataset.blockId;
            if (exceptBlockId && bid === exceptBlockId) return;
            menu.hidden = true;
            resetPickMenuPosition(menu);
        });
    }

    function togglePickMenu(blockId) {
        const menu = getPickMenu(blockId);
        if (!menu) return;
        const willOpen = menu.hidden;
        closeAllPickMenus();
        if (willOpen) {
            positionPickMenu(blockId);
            menu.hidden = false;
        }
    }

    function setupPickUi() {
        if (pickUiBound) return;
        pickUiBound = true;
        document.addEventListener('click', (e) => {
            const pickItem = e.target.closest('.pc-block-tagset-pick-item');
            if (pickItem) {
                e.preventDefault();
                e.stopPropagation();
                onSelectChange(pickItem.dataset.blockId, pickItem.dataset.collectionId);
                closeAllPickMenus();
                return;
            }
            if (!e.target.closest('.pc-block-tagset-pick')) {
                closeAllPickMenus();
            }
        });
        window.addEventListener('resize', () => closeAllPickMenus());
        window.addEventListener('scroll', () => closeAllPickMenus(), true);
    }

    function refreshBarsForBlockType(blockType, forceFetch) {
        const container = blocksContainer();
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
        const container = blocksContainer();
        if (!container) return;
        setupPickUi();
        try {
            await fetchCollections(false);
        } catch (err) {
            console.warn('[Prompt Composer] Block saves fetch failed:', err);
            return;
        }
        container.querySelectorAll('.pc-block-tagset-bar').forEach((bar) => {
            populateBarFromBlock(bar);
        });
    }

    function resolveCollectionId(blockId) {
        if (selectionState[blockId]?.collectionId) {
            return selectionState[blockId].collectionId;
        }
        const block = findBlock(blockId);
        if (!block) return '';
        const name = getEnteredName(blockId);
        if (!name) return '';
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
        const input = getNameInput(blockId);
        if (input) input.value = saved.name || name;
        setPickSelection(blockId, saved.id);

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
        if (block && normalizeBlockType(col.block) !== normalizeBlockType(block.type)) {
            const ok = confirm(
                `この保存は「${blockTypeLabel(col.block)}」用です。\n`
                + `現在の欄「${block.label}」に読み込みますか？`
            );
            if (!ok) return false;
        }
        const input = getNameInput(blockId);
        if (input) input.value = col.name || '';
        setPickSelection(blockId, collectionId);

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
        if (input) input.value = '';
        setPickSelection(blockId, '');
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
        togglePickMenu,
        onSelectChange,
        onNameInput: syncSelectToName
    };

    function init() {
        if (!window.PromptComposer) {
            setTimeout(init, 400);
            return;
        }
        setupPickUi();
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
    let refreshBarsDebounce = null;
    if (typeof onUiUpdate === 'function') {
        onUiUpdate(() => {
            if (refreshBarsDebounce) clearTimeout(refreshBarsDebounce);
            refreshBarsDebounce = setTimeout(() => {
                refreshBarsDebounce = null;
                refreshAllBlockTagSetBars();
            }, 800);
        });
    }
})();
