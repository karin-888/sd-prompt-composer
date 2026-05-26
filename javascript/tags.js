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
    let wildcardsLoaded = false;

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

    function markTagPreviewError(img) {
        if (!img) return;
        img.classList.add('pc-tag-preview-error');
        img.classList.remove('pc-tag-preview-pending');
        img.removeAttribute('src');
        const art = img.closest('.pc-tag-card-art');
        if (art) art.classList.add('is-preview-error');
        const card = img.closest('.pc-tag-card');
        if (card) card.classList.remove('has-preview');
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
        loadPathsAndInitialTags();
        console.log('[Prompt Composer] Tag dictionary initialized');
    }

    function renderWildcardsHint() {
        const wcHost = document.getElementById('pc_wildcards_container');
        if (!wcHost) return;
        wcHost.classList.add('pc-wc-container');
        wcHost.innerHTML = `
            <div class="pc-wc-header">🪄 Wildcards</div>
            <div class="pc-wc-more">ワイルドカード検索欄にキーワードを入力すると読み込みます（例: pose, hair, nsfw）。</div>
        `;
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
                const result = await fetchTagItems(q, null, null, null, 500, 0);
                currentItems = result.items;
                renderSearchResults(currentItems);
                return;
            }
            hideSearchResults();
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

    async function loadWildcards(query) {
        const q = (query || '').trim();
        if (!q && !wildcardsLoaded) {
            renderWildcardsHint();
            return;
        }
        try {
            const params = new URLSearchParams();
            if (query) params.set('q', query);
            params.set('limit', '5000');
            const resp = await fetch('/prompt-composer/api/wildcards?' + params.toString());
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            wildcardItems = data.items || [];
            wildcardSources = data.sources || [];
            wildcardsLoaded = true;
            renderWildcards(query || '');
        } catch (err) {
            wildcardItems = [];
            wildcardSources = [];
            renderWildcards(query || '');
        }
    }

    function buildWildcardTree(items) {
        const root = { name: '', path: '', children: new Map(), leaves: [] };
        (items || []).forEach(it => {
            const path = (it.path || '').trim();
            const token = (it.token || '').trim();
            if (!token) return;
            const parts = path ? path.split('/').filter(Boolean) : [token];
            let node = root;
            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                const isLeaf = (i === parts.length - 1);
                if (isLeaf) {
                    node.leaves.push({ label: part, path, token });
                } else {
                    if (!node.children.has(part)) {
                        const childPath = node.path ? `${node.path}/${part}` : part;
                        node.children.set(part, { name: part, path: childPath, children: new Map(), leaves: [] });
                    }
                    node = node.children.get(part);
                }
            }
        });
        return root;
    }

    function countTree(node) {
        let count = (node.leaves || []).length;
        node.children.forEach(child => { count += countTree(child); });
        return count;
    }

    function escapeHtmlAttr(str) {
        // escapeHtml is fine for attrs too (we use dataset), but keep explicit
        return escapeHtml(str);
    }

    function renderTreeNode(node, queryLower) {
        const children = Array.from(node.children.keys()).sort((a, b) => a.localeCompare(b, 'en'));
        const leaves = (node.leaves || []).slice().sort((a, b) => (a.label || '').localeCompare(b.label || '', 'en'));

        let html = '';

        // children
        children.forEach(name => {
            const child = node.children.get(name);
            const key = child.path;

            // auto expand when searching
            const shouldExpand = queryLower ? true : wcExpanded.has(key);
            const caret = shouldExpand ? '▾' : '▸';
            const childCount = countTree(child);

            html += `
                <div class="pc-wc-node" data-wc-node="${escapeHtmlAttr(key)}">
                    <button type="button" class="pc-wc-toggle" data-wc-toggle="${escapeHtmlAttr(key)}">
                        <span class="pc-wc-caret">${caret}</span>
                        <span class="pc-wc-folder">${escapeHtml(name)}</span>
                        <span class="pc-wc-count-mini">${childCount}</span>
                    </button>
                    <div class="pc-wc-children" style="display:${shouldExpand ? 'block' : 'none'}">
                        ${renderTreeNode(child, queryLower)}
                    </div>
                </div>
            `;
        });

        // leaves
        leaves.forEach(l => {
            const label = l.label || l.path || l.token;
            html += `<button type="button" class="pc-wc-leaf" data-token="${escapeHtmlAttr(l.token)}" title="${escapeHtmlAttr(l.token)}">${escapeHtml(label)}</button>`;
        });

        return html;
    }

    function renderWildcards(query) {
        const container = document.getElementById('pc_tags_container');
        if (!container) return;
        let wcHost = document.getElementById('pc_wildcards_container');
        if (!wcHost) {
            // Tabs内のDOMがまだマウントされていない可能性があるため、一定回数だけリトライ。
            if (wildcardRenderRetryCount < 20) {
                wildcardRenderRetryCount++;
                setTimeout(() => renderWildcards(query), 300);
            }
            return;
        }

        wildcardRenderRetryCount = 0;
        if (!wcHost.classList.contains('pc-wc-container')) {
            wcHost.classList.add('pc-wc-container');
        }

        if (!wildcardItems || wildcardItems.length === 0) {
            const srcText = (wildcardSources && wildcardSources.length)
                ? wildcardSources.map(s => escapeHtml(`${s.source}: ${s.dir}`)).join('<br>')
                : '';
            const q = (query || '').trim();
            const hint = q
                ? '一致するワイルドカードがありません。'
                : 'ワイルドカード検索欄にキーワードを入力してください（例: pose, hair, nsfw）。';
            wcHost.innerHTML = `
                <div class="pc-wc-header">🪄 Wildcards</div>
                <div class="pc-wc-more">${hint}</div>
                ${srcText ? `<div class="pc-wc-sources">${srcText}</div>` : ''}
            `;
            return;
        }

        const q = (query || '').trim();
        const qLower = q.toLowerCase();
        const tree = buildWildcardTree(wildcardItems);
        const total = wildcardItems.length;

        let html = `<div class="pc-wc-header">🪄 Wildcards <span class="pc-wc-count">(${total})</span></div>`;
        html += `<div class="pc-wc-tree">${renderTreeNode(tree, qLower)}</div>`;
        html += `<div class="pc-wc-more">クリックで挿入（例: <code>__POSES/all-fours__</code>）</div>`;
        wcHost.innerHTML = html;

        // toggle folder expand
        wcHost.querySelectorAll('.pc-wc-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.wcToggle;
                if (!key) return;
                if (wcExpanded.has(key)) wcExpanded.delete(key);
                else wcExpanded.add(key);
                renderWildcards(query || '');
            });
        });

        // leaf insert
        wcHost.querySelectorAll('.pc-wc-leaf').forEach(btn => {
            btn.addEventListener('click', () => {
                const token = btn.dataset.token;
                if (!token || !window.PromptComposer) return;
                const blocks = (window.PromptComposer.blocks || []).concat(window.PromptComposer.negativeBlocks || []);

                let target = null;
                const activeId = window.PromptComposerActiveBlockId;
                if (activeId) {
                    target = blocks.find(b => b.id === activeId);
                }
                if (!target) {
                    target = blocks.find(b => b.enabled) || blocks[0];
                }
                if (!target) return;

                window.PromptComposer.addToken(target.id, token, token, {
                    sourceType: 'manual',
                    isTrigger: false
                });
            });
        });
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
        const previewAttr = previewUrl ? ` data-preview-url="${escapeHtml(previewUrl)}"` : '';
        const hasPreview = Boolean(previewUrl);
        const art = hasPreview
            ? `<div class="pc-tag-card-art">
                    <img class="pc-tag-preview pc-tag-preview-pending" data-src="${escapeHtml(previewUrl)}" alt="" decoding="async" />
                    <span class="pc-tag-card-no-image">No image</span>
               </div>`
            : `<div class="pc-tag-card-art pc-tag-card-art-empty"><span class="pc-tag-card-art-icon" aria-hidden="true">🏷️</span></div>`;
        return `
            <button type="button" class="pc-tag-card${hasPreview ? ' has-preview' : ''}" data-tag="${tag}" data-jp="${jp}"${previewAttr}>
                ${art}
                <div class="pc-tag-card-body">
                    <span class="pc-tag-en" title="${tag}">${tag}</span>
                    ${jp ? `<span class="pc-tag-jp" title="${jp}">${jp}</span>` : ''}
                </div>
            </button>
        `;
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
            <div class="pc-tag-path-search-head">検索結果 (${items.length})</div>
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
        tagPathTreeHost.querySelectorAll('[data-tag-toggle]').forEach(btn => {
            const key = readPathKeyAttr(btn, 'data-tag-toggle');
            if (!key) return;
            const open = tagExpanded.has(key);
            const caret = btn.querySelector('.pc-wc-caret');
            if (caret) caret.textContent = open ? '▾' : '▸';
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
        hideSearchResults();
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
        const qLower = (qInput ? (qInput.value || '') : '').trim().toLowerCase();
        host.innerHTML = renderTagPathLevel(node, qLower);
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
                toggleTagPathNode(readPathKeyAttr(toggle, 'data-tag-toggle'));
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
            const select = e.target.closest('[data-tag-select]');
            if (select) {
                applyTagPathKey(readPathKeyAttr(select, 'data-tag-select'));
            }
        });
    }


    function setupSearch() {
        const tagRoot = document.getElementById('pc_tag_search');
        const wcRoot = document.getElementById('pc_wc_search');

        // Tag search: filters tags + also updates wildcards to keep behavior consistent.
        if (tagRoot) {
            const tagInput = tagRoot.querySelector('input') || tagRoot.querySelector('textarea');
            if (tagInput && tagInput.dataset.pcSearchBound !== '1') {
                tagInput.dataset.pcSearchBound = '1';
                ensureQuickInsertBar(tagRoot);
                tagInput.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    const value = e.target.value;
                    debounceTimer = setTimeout(() => {
                        const q = value.trim();
                        loadTags(q);
                        if (q) loadWildcards(q);
                    }, 250);
                });
            }
        }

        // Wildcard search: only filters wildcards.
        if (wcRoot) {
            const wcInput = wcRoot.querySelector('input') || wcRoot.querySelector('textarea');
            if (wcInput && wcInput.dataset.pcSearchBound !== '1') {
                wcInput.dataset.pcSearchBound = '1';
                wcInput.addEventListener('input', (e) => {
                    clearTimeout(wildcardDebounceTimer);
                    const value = e.target.value;
                    wildcardDebounceTimer = setTimeout(() => {
                        loadWildcards(value.trim());
                    }, 250);
                });
            }
        }
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
        const cached = tagLeavesCache.get(key);
        if (cached && cached.length) return cached.length;
        return tagPathCounts[key] || 0;
    }

    function nodeMatchesQuery(node, qLower) {
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

    function renderTagPathLevel(node, qLower) {
        const children = orderedTagPathChildKeys(node);
        let html = '';

        children.forEach(name => {
            const child = node.children.get(name);
            if (qLower && !nodeMatchesQuery(child, qLower)) return;

            const key = child.path;
            const pathAttr = encodePathKey(key);
            const hasChildren = child.children.size > 0;
            const isOpen = qLower ? true : tagExpanded.has(key);
            const caret = isOpen ? '▾' : '▸';
            const count = getTagPathCount(key);
            const isSelected = selectedPathKey === key;
            const displayName = tagPathDisplayLabel(name, key);

            html += '<div class="pc-wc-node">';
            html += `<div class="pc-tag-path-row${isSelected ? ' is-selected' : ''}">`;
            html += `
                <button type="button" class="pc-wc-toggle pc-tag-path-toggle" data-tag-toggle="${pathAttr}" title="展開 / 折りたたみ">
                    <span class="pc-wc-caret">${caret}</span>
                </button>`;
            html += `
                <button type="button" class="pc-tag-path-select" data-tag-select="${pathAttr}" title="${escapeHtml(displayName)}">
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
        const qLower = (qInput ? (qInput.value || '') : '').trim().toLowerCase();
        tagPathTreeRoot = buildTagPathTree(allPaths);
        let total = 0;
        tagPathTreeRoot.children.forEach(child => { total += getTagPathCount(child.path); });

        let html = `
            <div class="pc-tag-path-tree-head">
                <span class="pc-tag-path-tree-title">タグ辞書</span>
                <span class="pc-wc-count">(${total})</span>
                <button type="button" class="pc-tag-path-collapse-all" title="すべて閉じる" aria-label="すべて閉じる">
                    <span class="pc-tag-path-collapse-icon" aria-hidden="true">⊟</span>
                </button>
            </div>
            <div class="pc-tag-path-search-results" style="display:none"></div>
            <div class="pc-wc-tree pc-tag-path-tree">${renderTagPathLevel(tagPathTreeRoot, qLower)}</div>
            <div class="pc-wc-more">▸で展開 — フォルダ内にタグが表示されます</div>
        `;
        tagPathTreeHost.innerHTML = html;
        tagPathTreeScrollEl = tagPathTreeHost.querySelector('.pc-tag-path-tree');
        tagChildrenRendered = new Set();

        bindTagPathTreeEvents();
        syncTreeExpandState();
        updateTreeSelectionStyles();

        tagExpanded.forEach(key => {
            ensureNodeChildrenRendered(key);
            const cached = tagLeavesCache.get(key);
            const host = findLeavesHost(key);
            if (host && cached) {
                const state = tagPageState.get(key) || { total: cached.length, hasMore: false };
                host.innerHTML = renderTagLeavesPanel(key, cached, state.total, state.hasMore);
                host.dataset.loaded = '1';
                scheduleTagPreviewObserve(host);
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

