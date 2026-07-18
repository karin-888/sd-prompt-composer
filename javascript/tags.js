/**
 * Tag Dictionary Panel
 * Uses /prompt-composer/api/tags to provide a searchable list
 * of prompt tags with Japanese translations.
 */
(function() {
    'use strict';

    let currentItems = [];
    let debounceTimer = null;
    let wildcardDebounceTimer = null;
    let wildcardRenderRetryCount = 0;
    let currentSection = null;
    let currentCategory = null;
    let currentGroup = null;
    let allPaths = [];
    let sectionOrderByName = new Map();
    let tagPathCounts = {};
    let wildcardItems = [];
    let wildcardSources = [];
    let wcExpanded = new Set(); // expanded node keys (folder paths)
    let tagExpanded = new Set();
    let selectedPathKey = '';
    let tagPathTreeHost = null;
    let tagLeavesCache = new Map(); // pathKey -> items[]
    let tagPathTreeScrollEl = null;
    let tagPathTreeRoot = null;
    let tagChildrenRendered = new Set();
    let tagPageState = new Map(); // pathKey -> { items, total, hasMore }
    let searchHitCounts = null; // Map pathKey -> hit count (leaf + ancestors)
    let searchHitLeafKeys = null; // Set of leaf path keys that matched
    let searchHitTotal = 0;
    let wildcardsLoaded = false;
    let wildcardSearchQuery = '';
    let wildcardSearchDebounce = null;
    let selectedWildcardPath = '';
    let wildcardDirty = false;
    let wildcardEditorMode = 'edit'; // 'edit' | 'create'
    let wildcardRootPath = '';

    const TAG_PATH_SEP = '\x1f';
    const TAG_PAGE_SIZE = 120;
    const STAR_MARK_SECTIONS = new Set([
        'ai-nante',
        'naiv3_illustrious_artist_styles',
        'noplog',
        'note',
        'runrunsketch',
        'sorenuts'
    ]);

    function displayJpLabel(item) {
        const jp = (item && item.jp ? String(item.jp) : '').trim();
        if (/^(単体アーティスト|複数アーティスト)\s+No\.\d+\s*:/.test(jp)) {
            return '';
        }
        return jp;
    }

    function tagPathDisplayLabel(name, pathKey) {
        const label = (name || '').trim();
        if (!label) return label;
        const depth = splitTagPathKey(pathKey || label).length;
        if (depth === 1 && STAR_MARK_SECTIONS.has(label)) {
            return `★ ${label}`;
        }
        return label;
    }

    function splitTagPathKey(key) {
        return (key || '').split(TAG_PATH_SEP).filter(Boolean);
    }

    function makePathKey(sec, cat, grp) {
        const parts = [(sec || '').trim() || '(未分類)'];
        const c = (cat || '').trim();
        const g = (grp || '').trim();
        if (c) {
            parts.push(c);
            if (g) parts.push(g);
        }
        return parts.join(TAG_PATH_SEP);
    }

    function buildTagPathCountsFromEntries(entries, legacyCounts) {
        const map = {};
        (entries || []).forEach((entry) => {
            const key = makePathKey(entry.section, entry.category, entry.group);
            if (key) map[key] = Number(entry.count) || 0;
        });
        if (Object.keys(map).length === 0 && legacyCounts) {
            return legacyCounts;
        }
        return map;
    }

    function encodePathKey(key) {
        if (!key) return '';
        try {
            return btoa(unescape(encodeURIComponent(key)))
                .replace(/\+/g, '-')
                .replace(/\//g, '_')
                .replace(/=+$/, '');
        } catch (_) {
            return '';
        }
    }

    function decodePathKey(encoded) {
        const raw = (encoded || '').trim();
        if (!raw) return '';
        if (raw.includes(TAG_PATH_SEP)) return raw;
        try {
            let b64 = raw.replace(/-/g, '+').replace(/_/g, '/');
            while (b64.length % 4) b64 += '=';
            return decodeURIComponent(escape(atob(b64)));
        } catch (_) {
            return raw;
        }
    }

    function readPathKeyAttr(el, attr) {
        if (!el) return '';
        return decodePathKey(el.getAttribute(attr) || '');
    }

    function updatePathCountBadge(key, count) {
        if (!tagPathTreeHost || !key) return;
        tagPathCounts[key] = count;
        const encoded = encodePathKey(key);
        tagPathTreeHost.querySelectorAll('[data-tag-select]').forEach((btn) => {
            const attr = btn.getAttribute('data-tag-select') || '';
            if (attr !== encoded && decodePathKey(attr) !== key) return;
            const badge = btn.querySelector('.pc-wc-count-mini');
            if (badge) badge.textContent = String(count);
        });
    }

    function getTagPreviewObserver(root) {
        const key = root || document.documentElement;
        if (!getTagPreviewObserver._byRoot) getTagPreviewObserver._byRoot = new Map();
        const cached = getTagPreviewObserver._byRoot.get(key);
        if (cached) return cached;
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                loadTagPreviewImage(entry.target);
                observer.unobserve(entry.target);
            });
        }, { root: root || null, rootMargin: '200px 0px', threshold: 0.01 });
        getTagPreviewObserver._byRoot.set(key, observer);
        return observer;
    }

    function findScrollRoot(el) {
        let node = el.parentElement;
        while (node && node !== document.body) {
            const style = window.getComputedStyle(node);
            const scrollable = /(auto|scroll|overlay)/.test(style.overflowY)
                && node.scrollHeight > node.clientHeight + 8;
            if (scrollable) return node;
            node = node.parentElement;
        }
        return null;
    }

    function normalizePreviewUrl(url) {
        const raw = (url || '').trim();
        if (!raw) return '';
        try {
            const parsed = new URL(raw, window.location.origin);
            const tag = parsed.searchParams.get('tag');
            if (tag != null) {
                return `${parsed.pathname}?tag=${encodeURIComponent(tag)}`;
            }
        } catch (_) { /* ignore malformed URLs */ }
        return raw;
    }

    function markTagPreviewLoaded(img) {
        if (!img) return;
        img.classList.add('is-loaded');
        img.classList.remove('pc-tag-preview-pending', 'pc-tag-preview-error');
        const art = img.closest('.pc-tag-card-art');
        if (art) art.classList.remove('is-preview-error');
    }

    function collapseTagCardToTextOnly(card) {
        if (!card) return;
        card.classList.remove('has-preview');
        card.classList.add('pc-tag-card-text-only');
        card.removeAttribute('data-preview-url');
        let art = card.querySelector('.pc-tag-card-art');
        if (!art) {
            art = document.createElement('div');
            art.className = 'pc-tag-card-art pc-tag-card-art-empty';
            art.innerHTML = '<span class="pc-tag-card-no-image">No Image</span>';
            card.insertBefore(art, card.firstChild);
            return;
        }
        art.classList.add('pc-tag-card-art-empty', 'is-preview-error');
        art.innerHTML = '<span class="pc-tag-card-no-image">No Image</span>';
    }

    function markTagPreviewError(img) {
        if (!img) return;
        const card = img.closest('.pc-tag-card');
        collapseTagCardToTextOnly(card);
    }

    function loadTagPreviewImage(img) {
        if (!img || img.dataset.loaded === '1') return;
        const src = normalizePreviewUrl(img.dataset.src || '');
        if (!src) return;
        img.dataset.loaded = '1';
        img.addEventListener('load', () => markTagPreviewLoaded(img), { once: true });
        img.addEventListener('error', () => markTagPreviewError(img), { once: true });
        img.src = src;
        if (img.complete && img.naturalWidth > 0) {
            markTagPreviewLoaded(img);
        }
    }

    function observeTagPreviewImages(root) {
        if (!root) return;
        root.querySelectorAll('img.pc-tag-preview[data-src]:not([data-loaded])').forEach((img) => {
            const scrollRoot = findScrollRoot(img);
            getTagPreviewObserver(scrollRoot).observe(img);
        });
    }

    function scheduleTagPreviewObserve(root) {
        if (!root) return;
        requestAnimationFrame(() => observeTagPreviewImages(root));
    }

    function init() {
        const container = document.getElementById('pc_tags_container');
        if (!container) {
            setTimeout(init, 500);
            return;
        }

        setupSearch();
        hideTagsListContainer();
        reorderTagDictionaryLayout();
        renderWildcardsHint();
        loadWildcards('');
        loadPathsAndInitialTags();
        console.log('[Prompt Composer] Tag dictionary initialized');
    }

    function renderWildcardsHint() {
        const wcHost = document.getElementById('pc_wildcards_container');
        if (!wcHost) return;
        wcHost.classList.add('pc-wc-container');
        wcHost.innerHTML = `
            <div class="pc-wc-header">🪄 Wildcards</div>
            <div class="pc-wc-more">読込中…（sd-dynamic-prompts/wildcards）</div>
        `;
    }

    async function loadWildcards(query, opts) {
        const options = opts || {};
        const force = !!options.force || !wildcardsLoaded;
        try {
            if (force) {
                const params = new URLSearchParams();
                params.set('limit', '8000');
                params.set('force', '1');
                const resp = await fetch('/prompt-composer/api/wildcards?' + params.toString());
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const data = await resp.json();
                wildcardItems = data.items || [];
                wildcardSources = data.sources || [];
                wildcardRootPath = data.root || '';
                wildcardsLoaded = true;
            }
            const wcInput = document.querySelector('#pc_wc_inline_search, #pc_wc_search input, #pc_wc_search textarea');
            const q = (query != null ? query : (wildcardSearchQuery || ((wcInput && wcInput.value) || ''))).trim();
            wildcardSearchQuery = q;
            renderWildcards(q);
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load wildcards:', err);
            wildcardItems = [];
            wildcardSources = [];
            wildcardsLoaded = false;
            const wcHost = document.getElementById('pc_wildcards_container');
            if (wcHost) {
                wcHost.classList.add('pc-wc-container');
                wcHost.innerHTML = `
                    <div class="pc-wc-header">🪄 Wildcards</div>
                    <div class="pc-wc-more">読込に失敗しました。extensions/sd-dynamic-prompts/wildcards を確認してください。</div>
                `;
            }
        }
    }

    function groupWildcardItems(items) {
        const groups = new Map();
        (items || []).forEach(it => {
            const path = (it.path || '').trim();
            if (!path) return;
            let group = 'その他';
            const slash = path.indexOf('/');
            if (slash > 0) {
                group = path.slice(0, slash);
            } else {
                const m = path.match(/^(\d{2})/);
                if (m) group = m[1];
            }
            if (!groups.has(group)) groups.set(group, []);
            groups.get(group).push(it);
        });
        const keys = Array.from(groups.keys()).sort((a, b) => {
            if (a === 'その他') return 1;
            if (b === 'その他') return -1;
            return a.localeCompare(b, 'en', { numeric: true });
        });
        return keys.map(k => {
            const list = groups.get(k).slice().sort((a, b) =>
                (a.path || '').localeCompare(b.path || '', 'en', { numeric: true })
            );
            return { name: k, items: list };
        });
    }

    function shortWildcardName(path) {
        const p = (path || '').trim();
        const slash = p.lastIndexOf('/');
        return slash >= 0 ? p.slice(slash + 1) : p;
    }

    function insertWildcardToken(token) {
        if (!token || !window.PromptComposer) return;
        const blocks = (window.PromptComposer.blocks || []).concat(window.PromptComposer.negativeBlocks || []);
        let target = null;
        const activeId = window.PromptComposerActiveBlockId;
        if (activeId) target = blocks.find(b => b.id === activeId);
        if (!target) target = blocks.find(b => b.enabled) || blocks[0];
        if (!target) return;
        window.PromptComposer.addToken(target.id, token, token, {
            sourceType: 'wildcard',
            isTrigger: false
        });
    }

    function confirmDiscardWildcardEdits() {
        if (!wildcardDirty) return true;
        return confirm('編集内容が保存されていません。破棄しますか？');
    }

    async function loadWildcardContent(path) {
        const p = (path || '').trim();
        if (!p) return;
        try {
            const resp = await fetch('/prompt-composer/api/wildcards/content?path=' + encodeURIComponent(p));
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            selectedWildcardPath = data.path || p;
            wildcardEditorMode = 'edit';
            wildcardDirty = false;
            fillWildcardEditor(data);
            updateWildcardTreeSelection();
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load wildcard content:', err);
            alert('ワイルドカードの読込に失敗しました: ' + p);
        }
    }

    function fillWildcardEditor(data) {
        const nameEl = document.getElementById('pc_wc_editor_name');
        const tokenEl = document.getElementById('pc_wc_editor_token');
        const pathInput = document.getElementById('pc_wc_new_path');
        const editPathInput = document.getElementById('pc_wc_edit_path');
        const textarea = document.getElementById('pc_wc_editor_text');
        const statusEl = document.getElementById('pc_wc_editor_status');
        const createRow = document.getElementById('pc_wc_create_row');
        const editMeta = document.getElementById('pc_wc_edit_meta');
        if (!textarea) return;

        if (wildcardEditorMode === 'create') {
            if (createRow) createRow.hidden = false;
            if (editMeta) editMeta.hidden = true;
            if (pathInput) pathInput.value = selectedWildcardPath || '';
            if (editPathInput) {
                editPathInput.value = '';
                editPathInput.disabled = true;
            }
            textarea.value = (data && data.content) || '';
            if (statusEl) statusEl.textContent = '新規作成 — 保存先: sd-dynamic-prompts/wildcards';
        } else {
            if (createRow) createRow.hidden = true;
            if (editMeta) editMeta.hidden = false;
            const path = data.path || selectedWildcardPath || '';
            if (nameEl) nameEl.textContent = path || '（未選択）';
            if (editPathInput) {
                editPathInput.disabled = !path;
                editPathInput.readOnly = false;
                editPathInput.value = path;
                editPathInput.oninput = () => {
                    const next = (editPathInput.value || '').trim().replace(/\.txt$/i, '');
                    const tok = document.getElementById('pc_wc_editor_token');
                    if (tok) tok.textContent = next ? `__${next}__` : '';
                };
            }
            if (tokenEl) tokenEl.textContent = data.token || (path ? `__${path}__` : '');
            textarea.value = (data && data.content) != null ? data.content : '';
            if (statusEl) {
                statusEl.textContent = wildcardRootPath
                    ? `保存先: ${wildcardRootPath}`
                    : '保存先: extensions/sd-dynamic-prompts/wildcards';
            }
        }
        wildcardDirty = false;
        textarea.oninput = () => {
            wildcardDirty = true;
            if (statusEl && !statusEl.textContent.includes('未保存')) {
                statusEl.textContent = (statusEl.textContent || '') + ' · 未保存';
            }
        };
    }

    function startCreateWildcard() {
        if (!confirmDiscardWildcardEdits()) return;
        wildcardEditorMode = 'create';
        selectedWildcardPath = '';
        fillWildcardEditor({ content: '' });
        updateWildcardTreeSelection();
        const pathInput = document.getElementById('pc_wc_new_path');
        if (pathInput) {
            pathInput.focus();
            pathInput.select();
        }
    }

    async function renameSelectedWildcard() {
        if (wildcardEditorMode === 'create' || !selectedWildcardPath) {
            alert('変更するワイルドカードを選択してください。');
            return;
        }
        const editPathInput = document.getElementById('pc_wc_edit_path');
        const statusEl = document.getElementById('pc_wc_editor_status');
        const newPath = ((editPathInput && editPathInput.value) || '').trim().replace(/\.txt$/i, '');
        if (!newPath) {
            alert('新しいファイル名を入力してください（例: 00color または colors/red）');
            return;
        }
        if (newPath === selectedWildcardPath) {
            if (statusEl) statusEl.textContent = 'ファイル名は変更されていません';
            return;
        }
        if (!confirm(`"${selectedWildcardPath}.txt" を "${newPath}.txt" に変更しますか？`)) return;

        try {
            const resp = await fetch('/prompt-composer/api/wildcards/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: selectedWildcardPath, newPath })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || ('HTTP ' + resp.status));
            }
            const renamedPath = data.path || newPath;
            // Update local list immediately so the left tree reflects the new name.
            const prevPath = selectedWildcardPath;
            wildcardItems = (wildcardItems || []).map((it) => {
                if ((it.path || '') !== prevPath) return it;
                return {
                    ...it,
                    path: renamedPath,
                    token: data.token || `__${renamedPath}__`
                };
            });
            selectedWildcardPath = renamedPath;
            wildcardEditorMode = 'edit';
            wildcardDirty = false;
            if (statusEl) statusEl.textContent = `名前を変更しました: ${selectedWildcardPath}`;
            wildcardsLoaded = false;
            await loadWildcards(wildcardSearchQuery, { force: true });
            await loadWildcardContent(selectedWildcardPath);
        } catch (err) {
            console.warn('[Prompt Composer] Failed to rename wildcard:', err);
            alert('名前変更に失敗しました: ' + (err && err.message ? err.message : err));
        }
    }

    async function saveWildcardEditor() {
        const textarea = document.getElementById('pc_wc_editor_text');
        const statusEl = document.getElementById('pc_wc_editor_status');
        if (!textarea) return;

        let path = selectedWildcardPath;
        if (wildcardEditorMode === 'create') {
            const pathInput = document.getElementById('pc_wc_new_path');
            path = ((pathInput && pathInput.value) || '').trim();
            if (!path) {
                alert('ファイル名を入力してください（例: my_poses または folder/name）');
                return;
            }
        }
        if (!path) {
            alert('ワイルドカードを選択するか、新規作成してください。');
            return;
        }

        const content = textarea.value;
        const isCreate = wildcardEditorMode === 'create';
        const url = isCreate
            ? '/prompt-composer/api/wildcards/create'
            : '/prompt-composer/api/wildcards/content';

        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, content })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || ('HTTP ' + resp.status));
            }
            selectedWildcardPath = data.path || path;
            wildcardEditorMode = 'edit';
            wildcardDirty = false;
            if (statusEl) statusEl.textContent = '保存しました';
            wildcardsLoaded = false;
            await loadWildcards(wildcardSearchQuery);
            await loadWildcardContent(selectedWildcardPath);
        } catch (err) {
            console.warn('[Prompt Composer] Failed to save wildcard:', err);
            alert('保存に失敗しました: ' + (err && err.message ? err.message : err));
        }
    }

    async function deleteSelectedWildcard() {
        if (wildcardEditorMode === 'create' || !selectedWildcardPath) return;
        if (!confirm(`"${selectedWildcardPath}.txt" を削除しますか？`)) return;
        try {
            const resp = await fetch(
                '/prompt-composer/api/wildcards/content?path=' + encodeURIComponent(selectedWildcardPath),
                { method: 'DELETE' }
            );
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
            selectedWildcardPath = '';
            wildcardDirty = false;
            wildcardsLoaded = false;
            await loadWildcards('');
            fillWildcardEditor({ path: '', token: '', content: '' });
            const nameEl = document.getElementById('pc_wc_editor_name');
            const tokenEl = document.getElementById('pc_wc_editor_token');
            if (nameEl) nameEl.textContent = '（未選択）';
            if (tokenEl) tokenEl.textContent = '';
        } catch (err) {
            alert('削除に失敗しました: ' + (err && err.message ? err.message : err));
        }
    }

    function updateWildcardTreeSelection() {
        const host = document.getElementById('pc_wildcards_container');
        if (!host) return;
        host.querySelectorAll('.pc-file-tree-item').forEach(btn => {
            const p = btn.getAttribute('data-wc-path') || '';
            btn.classList.toggle('is-selected', p === selectedWildcardPath && wildcardEditorMode === 'edit');
        });
    }

    function renderWildcards(query) {
        let wcHost = document.getElementById('pc_wildcards_container');
        if (!wcHost) {
            if (wildcardRenderRetryCount < 20) {
                wildcardRenderRetryCount++;
                setTimeout(() => renderWildcards(query), 300);
            }
            return;
        }

        wildcardRenderRetryCount = 0;
        wcHost.classList.add('pc-wc-container');

        const activeBefore = document.activeElement;
        const keepSearchFocus = !!(activeBefore && activeBefore.id === 'pc_wc_inline_search');
        const prevSearchEl = document.getElementById('pc_wc_inline_search');
        const prevSelStart = prevSearchEl ? prevSearchEl.selectionStart : null;
        const prevSelEnd = prevSearchEl ? prevSearchEl.selectionEnd : null;

        const q = (query != null ? query : wildcardSearchQuery).trim();
        wildcardSearchQuery = q;
        const qLower = q.toLowerCase();
        const filtered = qLower
            ? (wildcardItems || []).filter(it => {
                const hay = ((it.path || '') + ' ' + (it.token || '')).toLowerCase();
                return hay.includes(qLower);
            })
            : (wildcardItems || []);
        const groups = groupWildcardItems(filtered);
        const total = filtered.length;
        if (!qLower && !wcExpanded.size && groups.length) {
            wcExpanded.add(groups[0].name);
        }
        const prevText = (document.getElementById('pc_wc_editor_text') || {}).value;
        const prevPathInput = (document.getElementById('pc_wc_new_path') || {}).value;
        const keepEditor = !!document.getElementById('pc_wc_editor_text');
        const wasDirty = wildcardDirty;

        let treeHtml = '';
        if (!groups.length) {
            treeHtml = `<div class="pc-wc-more">${q ? '一致するワイルドカードがありません。' : 'ワイルドカードがありません。'}</div>`;
        } else {
            groups.forEach(group => {
                const hasSelected = selectedWildcardPath && group.items.some(it => it.path === selectedWildcardPath);
                const open = qLower ? true : (wcExpanded.has(group.name) || !!hasSelected);
                if (open) wcExpanded.add(group.name);
                const items = group.items;
                treeHtml += `
                    <div class="pc-file-tree-folder${open ? ' is-open' : ''}" data-wc-folder="${escapeHtmlAttr(group.name)}">
                        <button type="button" class="pc-file-tree-folder-head" data-wc-folder-toggle="${escapeHtmlAttr(group.name)}">
                            <span class="pc-file-tree-caret">${open ? '▾' : '▸'}</span>
                            <span class="pc-file-tree-folder-name">${escapeHtml(group.name)}</span>
                            <span class="pc-file-tree-count">${items.length}</span>
                        </button>
                        <div class="pc-file-tree-children"${open ? '' : ' hidden'}>
                `;
                items.forEach((it, idx) => {
                    const path = it.path || '';
                    const branch = idx === items.length - 1 ? '└──' : '├──';
                    const isSel = path === selectedWildcardPath && wildcardEditorMode === 'edit';
                    treeHtml += `
                        <button type="button"
                            class="pc-file-tree-item${isSel ? ' is-selected' : ''}"
                            data-wc-path="${escapeHtmlAttr(path)}"
                            data-wc-token="${escapeHtmlAttr(it.token || '')}"
                            title="${escapeHtmlAttr(it.token || path)}">
                            <span class="pc-file-tree-branch" aria-hidden="true">${branch}</span>
                            <span class="pc-file-tree-item-main">
                                <span class="pc-file-tree-col-name">${escapeHtml(shortWildcardName(path))}</span>
                            </span>
                        </button>
                    `;
                });
                treeHtml += `</div></div>`;
            });
        }

        const editorName = selectedWildcardPath || '（未選択）';
        const editorToken = selectedWildcardPath ? `__${selectedWildcardPath}__` : '';
        const isCreate = wildcardEditorMode === 'create';

        wcHost.innerHTML = `
            <div class="pc-wc-header">
                <span>🪄 Wildcards <span class="pc-wc-count">(${total})</span></span>
                <button type="button" class="pc-wc-new-btn" id="pc_wc_btn_new" title="新規ワイルドカード">＋ 新規</button>
            </div>
            <div class="pc-wc-search-wrap">
                <input type="search" id="pc_wc_inline_search" class="pc-wc-inline-search"
                    placeholder="Wildcards（.txt）を検索..."
                    value="${escapeHtmlAttr(q)}"
                    autocomplete="off" spellcheck="false" />
                <button type="button" class="pc-wc-search-clear" id="pc_wc_search_clear"
                    title="検索をクリア" aria-label="検索をクリア"${q ? '' : ' hidden'}>
                    <span aria-hidden="true">×</span>
                </button>
            </div>
            <div class="pc-wc-layout">
                <div class="pc-wc-col-tree">
                    <div class="pc-file-tree" role="tree" aria-label="ワイルドカード一覧">
                        ${treeHtml}
                    </div>
                </div>
                <div class="pc-wc-col-editor">
                    <div class="pc-wc-editor-toolbar">
                        <div class="pc-wc-edit-meta" id="pc_wc_edit_meta"${isCreate ? ' hidden' : ''}>
                            <label class="pc-wc-edit-path-label" for="pc_wc_edit_path">ファイル名</label>
                            <input type="text" id="pc_wc_edit_path" class="pc-wc-edit-path"
                                placeholder="例: 00color または colors/red"
                                value="${escapeHtmlAttr(editorName === '（未選択）' ? '' : editorName)}"
                                autocomplete="off" spellcheck="false" />
                            <code class="pc-wc-editor-token" id="pc_wc_editor_token">${escapeHtml(editorToken)}</code>
                            <span class="pc-wc-editor-name" id="pc_wc_editor_name" hidden>${escapeHtml(editorName)}</span>
                        </div>
                        <div class="pc-wc-create-row" id="pc_wc_create_row"${isCreate ? '' : ' hidden'}>
                            <label class="pc-wc-create-label" for="pc_wc_new_path">ファイル名</label>
                            <input type="text" id="pc_wc_new_path" class="pc-wc-new-path"
                                placeholder="例: my_poses または poses/standing"
                                value="${escapeHtmlAttr(isCreate ? (prevPathInput || '') : '')}" />
                            <span class="pc-wc-create-hint">.txt は自動付与</span>
                        </div>
                        <div class="pc-file-tree-actions pc-wc-editor-actions">
                            <button type="button" id="pc_wc_btn_save" title="内容を保存">保存</button>
                            <button type="button" id="pc_wc_btn_rename" title="ファイル名を変更">名前変更</button>
                            <button type="button" id="pc_wc_btn_insert" title="プロンプトに挿入">挿入</button>
                            <button type="button" id="pc_wc_btn_delete" title="削除">削除</button>
                        </div>
                    </div>
                    <textarea id="pc_wc_editor_text" class="pc-wc-editor-text" spellcheck="false"
                        placeholder="1行に1エントリ（dynamic prompts 形式）"></textarea>
                    <div class="pc-wc-editor-status" id="pc_wc_editor_status"></div>
                </div>
            </div>
        `;

        const searchInput = document.getElementById('pc_wc_inline_search');
        const searchClear = document.getElementById('pc_wc_search_clear');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(wildcardSearchDebounce);
                const value = searchInput.value || '';
                if (searchClear) searchClear.hidden = !value.trim();
                wildcardSearchDebounce = setTimeout(() => {
                    wildcardSearchQuery = value.trim();
                    renderWildcards(wildcardSearchQuery);
                }, 180);
            });
            if (keepSearchFocus) {
                searchInput.focus();
                if (prevSelStart != null && prevSelEnd != null) {
                    try { searchInput.setSelectionRange(prevSelStart, prevSelEnd); } catch (_) { /* ignore */ }
                }
            }
        }
        if (searchClear) {
            searchClear.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                clearTimeout(wildcardSearchDebounce);
                wildcardSearchQuery = '';
                renderWildcards('');
                const again = document.getElementById('pc_wc_inline_search');
                if (again) again.focus();
            });
        }

        // Restore editor across tree re-renders; load from API only on first mount / new selection.
        if (keepEditor) {
            if (wildcardEditorMode === 'create') {
                fillWildcardEditor({ content: prevText || '' });
                const pathInput = document.getElementById('pc_wc_new_path');
                if (pathInput && prevPathInput != null) pathInput.value = prevPathInput;
            } else {
                fillWildcardEditor({
                    path: selectedWildcardPath,
                    token: selectedWildcardPath ? `__${selectedWildcardPath}__` : '',
                    content: prevText || ''
                });
            }
            wildcardDirty = wasDirty;
            const statusEl = document.getElementById('pc_wc_editor_status');
            if (statusEl && wasDirty && !String(statusEl.textContent || '').includes('未保存')) {
                statusEl.textContent = (statusEl.textContent || '') + ' · 未保存';
            }
        } else if (selectedWildcardPath && wildcardEditorMode === 'edit') {
            loadWildcardContent(selectedWildcardPath);
        } else {
            fillWildcardEditor({
                path: selectedWildcardPath,
                token: selectedWildcardPath ? `__${selectedWildcardPath}__` : '',
                content: ''
            });
        }

        // Ensure rename field is editable after tree re-renders.
        const editPathAfter = document.getElementById('pc_wc_edit_path');
        if (editPathAfter) {
            const canEdit = wildcardEditorMode === 'edit' && !!selectedWildcardPath;
            editPathAfter.disabled = !canEdit;
            editPathAfter.readOnly = false;
        }

        wcHost.querySelectorAll('[data-wc-folder-toggle]').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-wc-folder-toggle');
                if (!key) return;
                if (wcExpanded.has(key)) wcExpanded.delete(key);
                else wcExpanded.add(key);
                renderWildcards(wildcardSearchQuery);
            });
        });

        wcHost.querySelectorAll('.pc-file-tree-item[data-wc-path]').forEach(btn => {
            btn.addEventListener('click', () => {
                const path = btn.getAttribute('data-wc-path') || '';
                if (!path) return;
                if (path === selectedWildcardPath && wildcardEditorMode === 'edit') return;
                if (!confirmDiscardWildcardEdits()) return;
                loadWildcardContent(path);
            });
            btn.addEventListener('dblclick', () => {
                const token = btn.getAttribute('data-wc-token') || '';
                if (token) insertWildcardToken(token);
            });
        });

        const btnNew = document.getElementById('pc_wc_btn_new');
        const btnSave = document.getElementById('pc_wc_btn_save');
        const btnRename = document.getElementById('pc_wc_btn_rename');
        const btnInsert = document.getElementById('pc_wc_btn_insert');
        const btnDelete = document.getElementById('pc_wc_btn_delete');
        if (btnNew) btnNew.addEventListener('click', startCreateWildcard);
        if (btnSave) btnSave.addEventListener('click', saveWildcardEditor);
        if (btnRename) btnRename.addEventListener('click', renameSelectedWildcard);
        if (btnInsert) {
            btnInsert.addEventListener('click', () => {
                const token = selectedWildcardPath
                    ? `__${selectedWildcardPath}__`
                    : ((document.getElementById('pc_wc_editor_token') || {}).textContent || '').trim();
                if (token) insertWildcardToken(token);
            });
        }
        if (btnDelete) btnDelete.addEventListener('click', deleteSelectedWildcard);
    }

    function sectionNameFromPathKey(key) {
        const parts = splitTagPathKey(key);
        if (!parts.length) return '';
        return parts[0] === '(未分類)' ? '' : parts[0];
    }

    async function preloadTagSection(sectionName) {
        const name = (sectionName || '').trim();
        if (!name) return;
        try {
            await fetch(
                '/prompt-composer/api/tags/sections/load?section=' + encodeURIComponent(name),
                { method: 'POST' }
            );
        } catch (err) {
            console.warn('[Prompt Composer] Section preload failed:', name, err);
        }
    }

    async function loadPathsAndInitialTags() {
        try {
            const resp = await fetch('/prompt-composer/api/tag-paths');
            if (resp.ok) {
                const data = await resp.json();
                setupPathSelector(data.paths || [], data.counts || {}, data.pathCounts || [], data.sections || []);
            }
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load tag paths:', err);
        }
    }

    async function fetchTagItems(query, sec, cat, grp, limit, offset) {
        const params = new URLSearchParams();
        if (query) params.set('q', query);
        if (sec) params.set('section', sec);
        if (cat) params.set('category', cat);
        if (grp) params.set('group', grp);
        params.set('limit', String(limit || TAG_PAGE_SIZE));
        params.set('offset', String(offset || 0));
        const resp = await fetch('/prompt-composer/api/tags?' + params.toString());
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const items = (data.items || []).slice();
        return {
            items,
            total: Number(data.total) || items.length,
            hasMore: !!data.hasMore,
        };
    }

    async function loadTags(query) {
        const q = (query || '').trim();
        try {
            if (q) {
                await applySearchTreeFilter(q);
                return;
            }
            clearSearchTreeFilter();
            hideSearchResults();
            renderTagPathTreeUI(true);
            if (selectedPathKey) {
                tagLeavesCache.delete(selectedPathKey);
                tagPageState.delete(selectedPathKey);
                const host = findLeavesHost(selectedPathKey);
                if (host) host.dataset.loaded = '';
                await ensureNodeTagsLoaded(selectedPathKey, true, false);
            }
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load tags:', err);
        }
    }

    function clearSearchTreeFilter() {
        searchHitCounts = null;
        searchHitLeafKeys = null;
        searchHitTotal = 0;
    }

    function buildSearchHitMaps(paths) {
        const leafCounts = new Map();
        const allCounts = new Map();
        const leafKeys = new Set();
        (paths || []).forEach((entry) => {
            const key = makePathKey(entry.section, entry.category, entry.group);
            const count = Number(entry.count) || 0;
            if (!key || count <= 0) return;
            leafKeys.add(key);
            leafCounts.set(key, count);
            const parts = splitTagPathKey(key);
            let acc = '';
            parts.forEach((part) => {
                acc = acc ? `${acc}${TAG_PATH_SEP}${part}` : part;
                allCounts.set(acc, (allCounts.get(acc) || 0) + count);
            });
        });
        searchHitLeafKeys = leafKeys;
        searchHitCounts = allCounts;
    }

    async function applySearchTreeFilter(query) {
        const q = (query || '').trim();
        if (!q) {
            clearSearchTreeFilter();
            hideSearchResults();
            renderTagPathTreeUI(true);
            return;
        }
        const resp = await fetch(
            '/prompt-composer/api/tag-path-hits?q=' + encodeURIComponent(q)
        );
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        searchHitTotal = Number(data.total) || 0;
        buildSearchHitMaps(data.paths || []);
        tagLeavesCache = new Map();
        tagPageState = new Map();
        tagChildrenRendered = new Set();

        tagExpanded = new Set();
        (data.paths || []).forEach((entry) => {
            const key = makePathKey(entry.section, entry.category, entry.group);
            if (!key) return;
            const parts = splitTagPathKey(key);
            // Open folders that lead to hits, but keep leaf closed until clicked.
            let acc = '';
            for (let i = 0; i < Math.max(0, parts.length - 1); i++) {
                acc = acc ? `${acc}${TAG_PATH_SEP}${parts[i]}` : parts[i];
                tagExpanded.add(acc);
            }
            if (parts.length === 1) tagExpanded.add(parts[0]);
        });

        renderSearchFilterBanner(q, searchHitTotal);
        renderTagPathTreeUI(true);
    }

    function renderSearchFilterBanner(query, total) {
        if (!tagPathTreeHost) return;
        const box = tagPathTreeHost.querySelector('.pc-tag-path-search-results');
        if (!box) return;
        box.style.display = 'block';
        if (!total) {
            box.innerHTML = `<div class="pc-tag-path-search-head">「${escapeHtml(query)}」に一致するタグはありません</div>`;
            return;
        }
        box.innerHTML = `
            <div class="pc-tag-path-search-head">
                「${escapeHtml(query)}」の絞り込み — タグ数：${total}
                <span class="pc-tag-path-search-hint">下のフォルダを開くと該当タグだけ表示されます</span>
            </div>
        `;
    }

    function escapeHtmlAttr(str) {
        // escapeHtml is fine for attrs too (we use dataset), but keep explicit
        return escapeHtml(str);
    }

    function hideTagsListContainer() {
        const container = document.getElementById('pc_tags_container');
        if (container) container.innerHTML = '';
        const listWrap = document.getElementById('pc_tag_list');
        if (listWrap) listWrap.classList.add('pc-tag-list-embedded');
    }

    function insertTagFromRow(btn) {
        const tag = btn.dataset.tag;
        if (!tag || !window.PromptComposer) return;
        const jp = displayJpLabel({ jp: btn.dataset.jp || '' });
        const blocks = (window.PromptComposer.blocks || []).concat(window.PromptComposer.negativeBlocks || []);
        let target = null;
        const activeId = window.PromptComposerActiveBlockId;
        if (activeId) target = blocks.find(b => b.id === activeId);
        if (!target) target = blocks.find(b => b.enabled) || blocks[0];
        if (!target) return;
        window.PromptComposer.addToken(target.id, tag, tag, {
            sourceType: 'dict',
            isTrigger: false,
            jp: jp || null,
            previewUrl: (btn.dataset.previewUrl || '').trim() || null
        });
    }

    function renderTagCard(item) {
        const tag = escapeHtml(item.tag);
        const jp = escapeHtml(displayJpLabel(item));
        const previewUrl = normalizePreviewUrl(item.previewUrl || '');
        const body = `
                <div class="pc-tag-card-body">
                    <span class="pc-tag-en" title="${tag}">${tag}</span>
                    ${jp ? `<span class="pc-tag-jp" title="${jp}">${jp}</span>` : ''}
                </div>`;
        if (!previewUrl) {
            return `
            <button type="button" class="pc-tag-card pc-tag-card-text-only" data-tag="${tag}" data-jp="${jp}">
                <div class="pc-tag-card-art pc-tag-card-art-empty">
                    <span class="pc-tag-card-no-image">No Image</span>
                </div>
                ${body}
            </button>`;
        }
        const previewAttr = ` data-preview-url="${escapeHtml(previewUrl)}"`;
        return `
            <button type="button" class="pc-tag-card has-preview" data-tag="${tag}" data-jp="${jp}"${previewAttr}>
                <div class="pc-tag-card-art">
                    <img class="pc-tag-preview pc-tag-preview-pending" data-src="${escapeHtml(previewUrl)}" alt="" decoding="async" />
                    <span class="pc-tag-card-no-image">No Image</span>
                </div>
                ${body}
            </button>`;
    }

    function renderTagLeavesHtml(items) {
        if (!items || !items.length) {
            return '<div class="pc-empty pc-tag-path-empty">タグがありません</div>';
        }
        return `<div class="pc-tag-card-grid">${items.map(renderTagCard).join('')}</div>`;
    }

    let tagPreviewFloatEl = null;

    function ensureTagPreviewFloat() {
        if (tagPreviewFloatEl) return tagPreviewFloatEl;
        tagPreviewFloatEl = document.createElement('div');
        tagPreviewFloatEl.id = 'pc_tag_preview_float';
        tagPreviewFloatEl.className = 'pc-tag-preview-float';
        tagPreviewFloatEl.innerHTML = '<img alt="" />';
        document.body.appendChild(tagPreviewFloatEl);
        return tagPreviewFloatEl;
    }

    function positionTagPreviewFloat(artEl, naturalW, naturalH) {
        const floatEl = ensureTagPreviewFloat();
        const rect = artEl.getBoundingClientRect();
        const maxW = Math.min(window.innerWidth - 16, Math.max(260, rect.width * 2.6));
        const maxH = Math.min(window.innerHeight - 16, window.innerHeight * 0.78);

        let floatW;
        let floatH;
        if (naturalW > 0 && naturalH > 0) {
            const aspect = naturalW / naturalH;
            floatW = maxW;
            floatH = floatW / aspect;
            if (floatH > maxH) {
                floatH = maxH;
                floatW = floatH * aspect;
            }
        } else {
            floatW = Math.min(240, Math.max(180, rect.width * 2.1));
            floatH = floatW * (4 / 3);
        }

        let left = rect.left + rect.width / 2 - floatW / 2;
        let top = rect.top - floatH - 10;
        if (top < 8) top = rect.bottom + 10;
        left = Math.max(8, Math.min(left, window.innerWidth - floatW - 8));
        top = Math.max(8, Math.min(top, window.innerHeight - floatH - 8));
        floatEl.style.width = `${floatW}px`;
        floatEl.style.height = `${floatH}px`;
        floatEl.style.left = `${left}px`;
        floatEl.style.top = `${top}px`;
    }

    function hideTagPreviewFloat() {
        if (tagPreviewFloatEl) tagPreviewFloatEl.classList.remove('is-visible');
    }

    function bindTagCardPreviewHover(host) {
        if (!host || host.dataset.previewHover === '1') return;
        host.dataset.previewHover = '1';
        const floatEl = ensureTagPreviewFloat();
        const floatImg = floatEl.querySelector('img');
        let activeArt = null;

        host.addEventListener('mouseover', (e) => {
            const art = e.target.closest('.pc-tag-card-art:not(.pc-tag-card-art-empty):not(.is-preview-error)');
            if (!art || !host.contains(art)) return;
            const img = art.querySelector('.pc-tag-preview');
            const card = art.closest('.pc-tag-card');
            const previewUrl = (card && card.dataset.previewUrl) || (img && img.dataset.src) || '';
            if (!img || !previewUrl) return;
            loadTagPreviewImage(img);
            activeArt = art;
            const showFloat = () => {
                if (activeArt !== art) return;
                positionTagPreviewFloat(
                    art,
                    floatImg.naturalWidth,
                    floatImg.naturalHeight
                );
                floatEl.classList.add('is-visible');
            };
            floatImg.onload = showFloat;
            floatImg.src = img.src || previewUrl;
            if (floatImg.complete && floatImg.naturalWidth > 0) {
                showFloat();
            } else {
                positionTagPreviewFloat(art);
                floatEl.classList.add('is-visible');
            }
        });

        host.addEventListener('mouseout', (e) => {
            if (!activeArt) return;
            const related = e.relatedTarget;
            if (related && (activeArt.contains(related) || floatEl.contains(related))) return;
            activeArt = null;
            hideTagPreviewFloat();
        });

        window.addEventListener('scroll', hideTagPreviewFloat, true);
    }

    function findLeavesHost(key) {
        if (!tagPathTreeHost || !key) return null;
        const encoded = encodePathKey(key);
        for (const el of tagPathTreeHost.querySelectorAll('[data-tag-leaves]')) {
            const raw = el.getAttribute('data-tag-leaves') || '';
            if (raw === encoded || decodePathKey(raw) === key) return el;
        }
        return null;
    }

    function renderSearchResults(items) {
        if (!tagPathTreeHost) return;
        const box = tagPathTreeHost.querySelector('.pc-tag-path-search-results');
        if (!box) return;
        box.style.display = 'block';
        if (!items.length) {
            box.innerHTML = '<div class="pc-empty">タグが見つかりません</div>';
            return;
        }
        box.innerHTML = `
            <div class="pc-tag-path-search-head">検索結果　タグ数：${items.length}</div>
            <div class="pc-tag-path-leaves-inner">${renderTagLeavesHtml(items)}</div>
        `;
        scheduleTagPreviewObserve(box);
    }

    function hideSearchResults() {
        if (!tagPathTreeHost) return;
        const box = tagPathTreeHost.querySelector('.pc-tag-path-search-results');
        if (box) {
            box.style.display = 'none';
            box.innerHTML = '';
        }
    }

    function expandAncestors(key) {
        if (!key) return;
        const parts = splitTagPathKey(key);
        let acc = '';
        parts.forEach(p => {
            acc = acc ? `${acc}${TAG_PATH_SEP}${p}` : p;
            tagExpanded.add(acc);
        });
    }

    function syncTreeExpandState() {
        if (!tagPathTreeHost) return;
        tagPathTreeHost.querySelectorAll('.pc-tag-path-row [data-tag-select]').forEach(btn => {
            const key = readPathKeyAttr(btn, 'data-tag-select');
            if (!key) return;
            const row = btn.closest('.pc-tag-path-row');
            if (row) row.classList.toggle('is-open', tagExpanded.has(key));
        });
        tagPathTreeHost.querySelectorAll('[data-tag-children]').forEach(el => {
            const key = readPathKeyAttr(el, 'data-tag-children');
            el.style.display = tagExpanded.has(key) ? 'block' : 'none';
        });
        tagPathTreeHost.querySelectorAll('[data-tag-leaves]').forEach(el => {
            const key = readPathKeyAttr(el, 'data-tag-leaves');
            el.style.display = tagExpanded.has(key) ? 'block' : 'none';
        });
    }

    function updateTreeSelectionStyles() {
        if (!tagPathTreeHost) return;
        tagPathTreeHost.querySelectorAll('.pc-tag-path-row').forEach(row => {
            const select = row.querySelector('[data-tag-select]');
            const key = readPathKeyAttr(select, 'data-tag-select');
            row.classList.toggle('is-selected', key === selectedPathKey);
        });
    }

    function collapseAllTagPaths() {
        tagExpanded.clear();
        tagChildrenRendered.clear();
        selectedPathKey = '';
        currentSection = null;
        currentCategory = null;
        currentGroup = null;
        if (!searchHitCounts) hideSearchResults();
        syncTreeExpandState();
        updateTreeSelectionStyles();
    }

    function reorderTagDictionaryLayout() {
        const label = document.getElementById('pc_tag_path_label');
        const search = document.getElementById('pc_tag_search');
        const list = document.getElementById('pc_tag_list');
        if (!label || !search || !label.parentElement) return;
        const parent = label.parentElement;
        if (search.parentElement === parent && search.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING) {
            parent.insertBefore(search, label);
        }
        if (list && list.parentElement === parent) {
            parent.appendChild(list);
        }
    }

    function findChildrenHost(key) {
        if (!tagPathTreeHost || !key) return null;
        const encoded = encodePathKey(key);
        for (const el of tagPathTreeHost.querySelectorAll('[data-tag-children]')) {
            const raw = el.getAttribute('data-tag-children') || '';
            if (raw === encoded || decodePathKey(raw) === key) return el;
        }
        return null;
    }

    function findTreeNode(key) {
        if (!tagPathTreeRoot || !key) return null;
        const parts = splitTagPathKey(key);
        let node = tagPathTreeRoot;
        for (const part of parts) {
            if (!node || !node.children.has(part)) return null;
            node = node.children.get(part);
        }
        return node;
    }

    function ensureNodeChildrenRendered(key) {
        if (!key || tagChildrenRendered.has(key)) return;
        const node = findTreeNode(key);
        const host = findChildrenHost(key);
        if (!node || !host || !node.children.size) return;
        const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
        const qLower = searchHitCounts
            ? ''
            : ((qInput ? (qInput.value || '') : '').trim().toLowerCase());
        const depth = splitTagPathKey(key).length;
        host.innerHTML = renderTagPathLevel(node, qLower, depth);
        tagChildrenRendered.add(key);
        syncTreeExpandState();
        updateTreeSelectionStyles();
        if (tagExpanded.has(key) && !hasChildFoldersInDom(key)) {
            ensureNodeTagsLoaded(key, false, false);
        }
    }

    function renderTagLeavesPanel(key, items, total, hasMore) {
        let html = renderTagLeavesHtml(items);
        if (hasMore) {
            html += `<button type="button" class="pc-tag-load-more" data-tag-load-more="${encodePathKey(key)}">さらに表示 (${items.length}/${total})</button>`;
        }
        return `<div class="pc-tag-path-leaves-inner">${html}</div>`;
    }

    async function ensureNodeTagsLoaded(key, force, append) {
        if (!key || !tagPathTreeHost) return;
        const host = findLeavesHost(key);
        if (!host) return;
        if (!append && !force && host.dataset.loaded === '1') return;

        if (!append) {
            host.innerHTML = '<div class="pc-tag-path-loading">読込中…</div>';
            host.style.display = tagExpanded.has(key) ? 'block' : 'none';
        } else {
            const btn = host.querySelector('[data-tag-load-more]');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '読込中…';
            }
        }

        const f = filtersFromPathKey(key);
        const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
        const q = (qInput ? qInput.value : '').trim();
        const prev = tagPageState.get(key) || { items: [], total: 0, hasMore: false };
        const offset = append ? prev.items.length : 0;

        try {
            if (f.sec) await preloadTagSection(f.sec);
            const result = await fetchTagItems(q, f.sec, f.cat, f.grp, TAG_PAGE_SIZE, offset);
            const items = append ? prev.items.concat(result.items) : result.items;
            tagPageState.set(key, {
                items,
                total: result.total,
                hasMore: result.hasMore,
            });
            tagLeavesCache.set(key, items);
            host.innerHTML = renderTagLeavesPanel(key, items, result.total, result.hasMore);
            host.dataset.loaded = '1';
            updatePathCountBadge(key, result.total);
            scheduleTagPreviewObserve(host);
        } catch (err) {
            host.innerHTML = '<div class="pc-empty">読込に失敗しました</div>';
            console.warn('[Prompt Composer] Failed to load tags for path:', key, err);
        }
    }

    function hasChildFoldersInDom(key) {
        if (!tagPathTreeHost || !key) return false;
        for (const el of tagPathTreeHost.querySelectorAll('[data-tag-children]')) {
            const attrKey = readPathKeyAttr(el, 'data-tag-children');
            if (attrKey === key) return true;
        }
        return false;
    }

    function toggleTagPathNode(key) {
        if (!key) return;
        if (tagExpanded.has(key)) tagExpanded.delete(key);
        else tagExpanded.add(key);
        syncTreeExpandState();
        if (tagExpanded.has(key)) {
            ensureNodeChildrenRendered(key);
            if (splitTagPathKey(key).length === 1) {
                preloadTagSection(sectionNameFromPathKey(key));
            }
            if (!hasChildFoldersInDom(key)) {
                ensureNodeTagsLoaded(key, false, false);
            }
        }
    }

    function bindTagPathTreeEvents() {
        if (!tagPathTreeHost || tagPathTreeHost.dataset.bound === '1') return;
        tagPathTreeHost.dataset.bound = '1';
        bindTagCardPreviewHover(tagPathTreeHost);
        tagPathTreeHost.addEventListener('click', (e) => {
            const loadMore = e.target.closest('[data-tag-load-more]');
            if (loadMore) {
                e.preventDefault();
                e.stopPropagation();
                ensureNodeTagsLoaded(readPathKeyAttr(loadMore, 'data-tag-load-more'), false, true);
                return;
            }
            const toggle = e.target.closest('[data-tag-toggle]');
            if (toggle) {
                e.preventDefault();
                e.stopPropagation();
                const key = readPathKeyAttr(toggle, 'data-tag-toggle');
                toggleTagPathNode(key);
                selectedPathKey = key;
                const f = filtersFromPathKey(key);
                currentSection = f.sec;
                currentCategory = f.cat;
                currentGroup = f.grp;
                updateTreeSelectionStyles();
                return;
            }
            const tagBtn = e.target.closest('.pc-tag-card, .pc-tag-row');
            if (tagBtn) {
                e.preventDefault();
                e.stopPropagation();
                hideTagPreviewFloat();
                insertTagFromRow(tagBtn);
                return;
            }
            const collapseAll = e.target.closest('.pc-tag-path-collapse-all');
            if (collapseAll) {
                collapseAllTagPaths();
                return;
            }
            const select = e.target.closest('[data-tag-select]') || e.target.closest('.pc-tag-path-row')?.querySelector('[data-tag-select]');
            if (select && e.target.closest('.pc-tag-path-row')) {
                e.preventDefault();
                e.stopPropagation();
                const key = readPathKeyAttr(select, 'data-tag-select');
                toggleTagPathNode(key);
                selectedPathKey = key;
                const f = filtersFromPathKey(key);
                currentSection = f.sec;
                currentCategory = f.cat;
                currentGroup = f.grp;
                updateTreeSelectionStyles();
            }
        });
    }


    function setupSearch() {
        const tagRoot = document.getElementById('pc_tag_search');

        // Tag search: filters tag dictionary tree only (wildcards have their own inline search).
        if (tagRoot) {
            const tagInput = tagRoot.querySelector('input') || tagRoot.querySelector('textarea');
            if (tagInput && tagInput.dataset.pcSearchBound !== '1') {
                tagInput.dataset.pcSearchBound = '1';
                ensureQuickInsertBar(tagRoot);
                ensureTagSearchClearButton(tagRoot, tagInput);
                tagInput.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    syncTagSearchClearButton(tagRoot, e.target.value);
                    const value = e.target.value;
                    debounceTimer = setTimeout(() => {
                        loadTags(value.trim());
                    }, 250);
                });
                syncTagSearchClearButton(tagRoot, tagInput.value);
            }
        }
    }

    function getTagSearchFieldWrap(root) {
        if (!root) return null;
        return root.querySelector('.wrap') ||
            root.querySelector('.form') ||
            (root.querySelector('input, textarea') || {}).parentElement ||
            root;
    }

    function syncTagSearchClearButton(root, value) {
        if (!root) return;
        const btn = root.querySelector('.pc-tag-search-clear');
        if (!btn) return;
        const hasValue = !!(value || '').trim();
        btn.hidden = !hasValue;
        btn.setAttribute('aria-hidden', hasValue ? 'false' : 'true');
    }

    function ensureTagSearchClearButton(root, input) {
        if (!root || !input) return;
        if (root.querySelector('.pc-tag-search-clear')) return;

        const wrap = getTagSearchFieldWrap(root);
        if (!wrap) return;
        wrap.classList.add('pc-tag-search-field');

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'pc-tag-search-clear';
        btn.title = '検索をクリア';
        btn.setAttribute('aria-label', '検索をクリア');
        btn.innerHTML = '<span aria-hidden="true">×</span>';
        btn.hidden = true;
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            clearTagSearch(input, root);
        });
        wrap.appendChild(btn);
    }

    function clearTagSearch(input, root) {
        clearTimeout(debounceTimer);
        if (input) input.value = '';
        syncTagSearchClearButton(root || document.getElementById('pc_tag_search'), '');

        // Restore the full dictionary tree (initial browse state).
        tagExpanded.clear();
        tagChildrenRendered.clear();
        selectedPathKey = '';
        currentSection = null;
        currentCategory = null;
        currentGroup = null;
        tagLeavesCache = new Map();
        tagPageState = new Map();
        clearSearchTreeFilter();
        hideSearchResults();
        renderTagPathTreeUI(false);
        if (input && typeof input.focus === 'function') input.focus();
    }

    function ensureQuickInsertBar(root) {
        if (!root) return;
        if (root.querySelector('.pc-tag-dict-toolbar')) return;

        const toolbar = document.createElement('div');
        toolbar.className = 'pc-tag-dict-toolbar';

        const label = document.createElement('div');
        label.className = 'pc-tag-quicklabel';
        label.textContent = '特殊トークン';

        const bar = document.createElement('div');
        bar.className = 'pc-tag-quickbar';
        bar.innerHTML = `
            <button type="button" class="pc-tag-quickbtn" data-special="BREAK">BREAK</button>
            <button type="button" class="pc-tag-quickbtn" data-special="AND">AND</button>
        `;

        bar.addEventListener('click', (e) => {
            const el = e.target;
            if (!(el instanceof HTMLElement)) return;
            const kind = el.dataset.special;
            if (!kind) return;
            insertSpecial(kind);
        });

        toolbar.appendChild(label);
        toolbar.appendChild(bar);
        root.insertBefore(toolbar, root.firstChild);
    }

    function insertSpecial(kind) {
        if (!window.PromptComposer) return;
        const blocks = (window.PromptComposer.blocks || []).concat(window.PromptComposer.negativeBlocks || []);
        if (!blocks.length) return;

        // 1) Prefer last focused token input's block
        let target = null;
        const activeId = window.PromptComposerActiveBlockId;
        if (activeId) {
            target = blocks.find(b => b.id === activeId);
        }

        // 2) Fallback: subject block
        if (!target) {
            target = blocks.find(b => b.type === 'subject');
        }

        // 3) Fallback: first enabled positive block
        if (!target) {
            target = blocks.find(b => b.enabled) || blocks[0];
        }
        if (!target) return;

        window.PromptComposer.addToken(target.id, kind, kind, {
            sourceType: 'manual',
            isTrigger: false
        });
    }

    function buildTagPathTree(paths) {
        const root = { name: '', path: '', children: new Map(), pathData: null };
        (paths || []).forEach(p => {
            const sec = (p.section || '').trim() || '(未分類)';
            const cat = (p.category || '').trim();
            const grp = (p.group || '').trim();
            const parts = [sec];
            if (cat) parts.push(cat);
            if (grp) parts.push(grp);

            let node = root;
            let key = '';
            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                const isLast = i === parts.length - 1;
                key = key ? `${key}${TAG_PATH_SEP}${part}` : part;
                if (!node.children.has(part)) {
                    node.children.set(part, {
                        name: part,
                        path: key,
                        children: new Map(),
                        pathData: null
                    });
                }
                const child = node.children.get(part);
                if (isLast) child.pathData = p;
                node = child;
            }
        });
        return root;
    }

    function getTagPathCount(key) {
        if (!key) return 0;
        if (searchHitCounts) {
            return searchHitCounts.get(key) || 0;
        }
        const cached = tagLeavesCache.get(key);
        if (cached && cached.length) return cached.length;
        return tagPathCounts[key] || 0;
    }

    function nodeMatchesQuery(node, qLower) {
        if (searchHitCounts) {
            return (searchHitCounts.get(node.path) || 0) > 0;
        }
        if (!qLower) return true;
        if ((node.name || '').toLowerCase().includes(qLower)) return true;
        if (node.pathData) {
            const blob = [node.pathData.section, node.pathData.category, node.pathData.group]
                .join(' ')
                .toLowerCase();
            if (blob.includes(qLower)) return true;
        }
        let childHit = false;
        node.children.forEach(child => {
            if (nodeMatchesQuery(child, qLower)) childHit = true;
        });
        return childHit;
    }

    function filtersFromPathKey(key) {
        if (!key) return { sec: null, cat: null, grp: null };
        const parts = splitTagPathKey(key);
        const decode = (s) => (s === '(未分類)' ? '' : s);
        const sec = parts[0] ? decode(parts[0]) : '';
        const cat = parts[1] ? decode(parts[1]) : '';
        const grp = parts[2] ? decode(parts[2]) : '';
        return {
            sec: sec || null,
            cat: cat || null,
            grp: grp || null
        };
    }

    function sectionOrderIndex(sectionName) {
        const name = (sectionName || '').trim();
        if (!name) return 99999;
        if (sectionOrderByName.has(name)) return sectionOrderByName.get(name);
        return 99999;
    }

    function orderedTagPathChildKeys(node) {
        const keys = Array.from(node.children.keys());
        if (!node.path) {
            return keys.sort((a, b) => sectionOrderIndex(a) - sectionOrderIndex(b));
        }
        return keys;
    }

    function buildSectionOrderMap(sections) {
        sectionOrderByName = new Map();
        (sections || []).forEach((entry, idx) => {
            const name = (entry && entry.name ? String(entry.name) : '').trim();
            if (!name) return;
            const file = (entry && entry.file ? String(entry.file) : '').trim();
            const match = file.match(/sections\/(\d+)_/);
            const order = match ? parseInt(match[1], 10) : idx;
            sectionOrderByName.set(name, order);
        });
    }

    function renderTagPathLevel(node, qLower, depth = 0) {
        const children = orderedTagPathChildKeys(node);
        const visible = children.filter((name) => {
            const child = node.children.get(name);
            if (searchHitCounts) return nodeMatchesQuery(child, '');
            return !(qLower && !nodeMatchesQuery(child, qLower));
        });
        let html = '';

        visible.forEach((name, idx) => {
            const child = node.children.get(name);
            const key = child.path;
            const pathAttr = encodePathKey(key);
            const hasChildren = child.children.size > 0;
            const isOpen = searchHitCounts
                ? tagExpanded.has(key)
                : (qLower ? true : tagExpanded.has(key));
            const count = getTagPathCount(key);
            const isSelected = selectedPathKey === key;
            const displayName = tagPathDisplayLabel(name, key);
            const isRoot = depth === 0;
            const branch = isRoot ? '' : (idx === visible.length - 1 ? '└──' : '├──');

            html += `<div class="pc-wc-node${isRoot ? ' pc-tag-path-root' : ' pc-tag-path-child'}">`;
            html += `<div class="pc-tag-path-row pc-tag-path-depth-${depth}${isSelected ? ' is-selected' : ''}${isOpen ? ' is-open' : ''}${isRoot ? ' is-root' : ''}" data-depth="${depth}">`;
            if (branch) {
                html += `<span class="pc-file-tree-branch" aria-hidden="true">${branch}</span>`;
            }
            html += `
                <button type="button" class="pc-tag-path-select" data-tag-select="${pathAttr}" title="${escapeHtml(displayName)}（クリックで開閉）">
                    <span class="pc-wc-folder">${escapeHtml(displayName)}</span>
                    <span class="pc-wc-count-mini">${count}</span>
                </button>
            `;
            html += '</div>';
            if (hasChildren) {
                html += `<div class="pc-wc-children" data-tag-children="${pathAttr}" style="display:${isOpen ? 'block' : 'none'}"></div>`;
            } else {
                html += `<div class="pc-tag-path-leaves" data-tag-leaves="${pathAttr}" style="display:${isOpen ? 'block' : 'none'}"></div>`;
            }
            html += '</div>';
        });

        return html;
    }

    function applyTagPathSelection(sec, cat, grp, pathKey) {
        currentSection = sec;
        currentCategory = cat;
        currentGroup = grp;
        selectedPathKey = pathKey || '';

        if (pathKey) {
            expandAncestors(pathKey);
            tagExpanded.add(pathKey);
            let acc = '';
            splitTagPathKey(pathKey).forEach((part) => {
                acc = acc ? `${acc}${TAG_PATH_SEP}${part}` : part;
                ensureNodeChildrenRendered(acc);
            });
        }

        updateTreeSelectionStyles();
        syncTreeExpandState();

        const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
        const q = (qInput ? qInput.value : '').trim();
        if (q) {
            loadTags(q);
        } else if (pathKey) {
            ensureNodeChildrenRendered(pathKey);
            ensureNodeTagsLoaded(pathKey, true, false);
        }
    }

    function applyTagPathKey(key) {
        if (!key) {
            selectedPathKey = '';
            currentSection = null;
            currentCategory = null;
            currentGroup = null;
            hideSearchResults();
            updateTreeSelectionStyles();
            return;
        }
        const f = filtersFromPathKey(key);
        applyTagPathSelection(f.sec, f.cat, f.grp, key);
    }

    function renderTagPathTreeUI(preserveScroll) {
        if (!tagPathTreeHost) return;

        const scrollEl = tagPathTreeHost.querySelector('.pc-tag-path-tree');
        const scrollTop = preserveScroll && scrollEl ? scrollEl.scrollTop : 0;

        const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
        const qRaw = (qInput ? (qInput.value || '') : '').trim();
        const qLower = searchHitCounts ? '' : qRaw.toLowerCase();
        tagPathTreeRoot = buildTagPathTree(allPaths);
        let total = 0;
        if (searchHitCounts) {
            total = searchHitTotal;
        } else {
            tagPathTreeRoot.children.forEach(child => { total += getTagPathCount(child.path); });
        }

        let html = `
            <div class="pc-tag-path-tree-head">
                <span class="pc-tag-path-tree-title">タグ辞書</span>
                <span class="pc-wc-count">タグ数：${total}</span>
                <button type="button" class="pc-tag-path-collapse-all" title="すべて閉じる" aria-label="すべて閉じる">
                    <span class="pc-tag-path-collapse-icon" aria-hidden="true">⊟</span>
                </button>
            </div>
            <div class="pc-tag-path-search-results" style="display:none"></div>
            <div class="pc-wc-tree pc-tag-path-tree">${renderTagPathLevel(tagPathTreeRoot, qLower, 0)}</div>
            <div class="pc-wc-more">${searchHitCounts
                ? '一致するフォルダだけ表示中 — フォルダを開くと該当タグが出ます'
                : '名前をクリックで開閉 — フォルダ内にタグが表示されます'}</div>
        `;
        tagPathTreeHost.innerHTML = html;
        tagPathTreeScrollEl = tagPathTreeHost.querySelector('.pc-tag-path-tree');
        tagChildrenRendered = new Set();

        bindTagPathTreeEvents();
        syncTreeExpandState();
        updateTreeSelectionStyles();

        if (searchHitCounts && qRaw) {
            renderSearchFilterBanner(qRaw, searchHitTotal);
        }

        tagExpanded.forEach(key => {
            ensureNodeChildrenRendered(key);
            const cached = tagLeavesCache.get(key);
            const host = findLeavesHost(key);
            if (host && cached && !searchHitCounts) {
                const state = tagPageState.get(key) || { total: cached.length, hasMore: false };
                host.innerHTML = renderTagLeavesPanel(key, cached, state.total, state.hasMore);
                host.dataset.loaded = '1';
                scheduleTagPreviewObserve(host);
            } else if (host && searchHitCounts && tagExpanded.has(key) && !hasChildFoldersInDom(key)) {
                host.dataset.loaded = '';
                ensureNodeTagsLoaded(key, true, false);
            }
        });

        scheduleTagPreviewObserve(tagPathTreeHost);

        if (preserveScroll && tagPathTreeScrollEl) {
            tagPathTreeScrollEl.scrollTop = scrollTop;
        }
    }

    function setupPathSelector(paths, counts, pathCounts, sections) {
        const labelEl = document.getElementById('pc_tag_path_label');
        if (!labelEl) return;

        buildSectionOrderMap(sections);
        allPaths = (paths || []).slice();
        tagPathCounts = buildTagPathCountsFromEntries(pathCounts, counts || {});
        tagExpanded = new Set();
        tagLeavesCache = new Map();
        tagPageState = new Map();
        tagChildrenRendered = new Set();
        selectedPathKey = '';

        labelEl.innerHTML = '';
        tagPathTreeHost = document.createElement('div');
        tagPathTreeHost.className = 'pc-tag-path-tree-host';
        tagPathTreeHost.dataset.bound = '';
        labelEl.appendChild(tagPathTreeHost);

        renderTagPathTreeUI(false);
        hideTagsListContainer();
    }


    function updatePathLabel(items) {
        const labelEl = document.getElementById('pc_tag_path_label');
        if (!labelEl) return;
        // セレクタを使うようになったので、ここでは何もしない
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    window.PromptTags = {
        init,
        reload: () => {
            loadTags('');
            if (tagPathTreeHost) renderTagPathTreeUI(true);
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1500));
    } else {
        setTimeout(init, 1500);
    }

})();

