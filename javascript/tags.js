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
    let wildcardItems = [];
    let wildcardSources = [];
    let wcExpanded = new Set(); // expanded node keys (folder paths)

    function init() {
        const container = document.getElementById('pc_tags_container');
        if (!container) {
            setTimeout(init, 500);
            return;
        }

        setupSearch();
        loadWildcards('');
        loadPathsAndInitialTags();
        console.log('[Prompt Composer] Tag dictionary initialized');
    }

    async function loadPathsAndInitialTags() {
        try {
            const resp = await fetch('/prompt-composer/api/tag-paths');
            if (resp.ok) {
                const data = await resp.json();
                setupPathSelector(data.paths || []);
            }
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load tag paths:', err);
        }
        await loadTags('');
    }

    async function loadTags(query) {
        try {
            const params = new URLSearchParams();
            if (query) params.set('q', query);
            if (currentSection) params.set('section', currentSection);
            if (currentCategory) params.set('category', currentCategory);
            if (currentGroup) params.set('group', currentGroup);
            params.set('limit', '80');
            const resp = await fetch('/prompt-composer/api/tags?' + params.toString());
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            currentItems = (data.items || []).slice().sort((a, b) => {
                const aKey = (a.tag || '').toLowerCase();
                const bKey = (b.tag || '').toLowerCase();
                if (aKey < bKey) return -1;
                if (aKey > bKey) return 1;
                return 0;
            });
            renderList();
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load tags:', err);
        }
    }

    async function loadWildcards(query) {
        try {
            const params = new URLSearchParams();
            if (query) params.set('q', query);
            params.set('limit', '2000');
            const resp = await fetch('/prompt-composer/api/wildcards?' + params.toString());
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            wildcardItems = data.items || [];
            wildcardSources = data.sources || [];
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
            wcHost.innerHTML = `
                <div class="pc-wc-header">🪄 Wildcards <span class="pc-wc-count">(0)</span></div>
                <div class="pc-wc-more">wildcards（.txt）が見つかりませんでした。</div>
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

    function renderList() {
        const container = document.getElementById('pc_tags_container');
        if (!container) return;

        if (!currentItems.length) {
            container.innerHTML = '<div class="pc-empty">タグが見つかりません</div>';
            return;
        }

        // Group by section/category/group for hierarchical view
        const tree = {};
        currentItems.forEach(item => {
            const section = item.section || 'その他';
            const category = item.category || '';
            const group = item.group || '';
            tree[section] = tree[section] || {};
            tree[section][category] = tree[section][category] || {};
            tree[section][category][group] = tree[section][category][group] || [];
            tree[section][category][group].push(item);
        });

        let html = '<div class="pc-taglist">';
        // Compute common path to show above list
        updatePathLabel(currentItems);
        Object.keys(tree).forEach(section => {
            html += `<div class="pc-tag-section">
                <div class="pc-tag-section-header">${escapeHtml(section)}</div>
                <div class="pc-tag-section-body">
            `;
            const cats = tree[section];
            Object.keys(cats).forEach(cat => {
                if (cat) {
                    html += `<div class="pc-tag-category">
                        <div class="pc-tag-category-header">${escapeHtml(cat)}</div>
                        <div class="pc-tag-category-body">
                    `;
                }
                const groups = cats[cat];
                Object.keys(groups).forEach(group => {
                    if (group) {
                        html += `<div class="pc-tag-group">
                            <div class="pc-tag-group-header">${escapeHtml(group)}</div>
                            <div class="pc-tag-group-body">
                        `;
                    }
                    groups[group].forEach(item => {
                        const tag = escapeHtml(item.tag);
                        const jp = escapeHtml(item.jp || '');
                        html += `
                            <button class="pc-tag-row" data-tag="${tag}" data-jp="${jp}">
                                <div class="pc-tag-main">
                                    <span class="pc-tag-en">${tag}</span>
                                    ${jp ? `<span class="pc-tag-jp">${jp}</span>` : ''}
                                </div>
                            </button>
                        `;
                    });
                    if (group) {
                        html += '</div></div>'; // group-body + group
                    }
                });
                if (cat) {
                    html += '</div></div>'; // category-body + category
                }
            });
            html += '</div></div>'; // section-body + section
        });
        html += '</div>';

        container.innerHTML = html;

        container.querySelectorAll('.pc-tag-row').forEach(btn => {
            btn.addEventListener('click', () => {
                const tag = btn.dataset.tag;
                if (!tag || !window.PromptComposer) return;
                const jp = (btn.dataset.jp || '').trim();

                const blocks = (window.PromptComposer.blocks || []).concat(window.PromptComposer.negativeBlocks || []);

                // 1) Prefer last focused token input's block
                let target = null;
                const activeId = window.PromptComposerActiveBlockId;
                if (activeId) {
                    target = blocks.find(b => b.id === activeId);
                }

                // 2) Fallback: first enabled positive block
                if (!target) {
                    target = blocks.find(b => b.enabled) || blocks[0];
                }

                if (!target) return;

                window.PromptComposer.addToken(target.id, tag, tag, {
                    sourceType: 'dict',
                    isTrigger: false,
                    jp: jp || null
                });
            });
        });
    }

    function setupSearch() {
        const tagRoot = document.getElementById('pc_tag_search');
        const wcRoot = document.getElementById('pc_wc_search');

        // Tag search: filters tags + also updates wildcards to keep behavior consistent.
        if (tagRoot) {
            const tagInput = tagRoot.querySelector('input') || tagRoot.querySelector('textarea');
            if (tagInput) {
                ensureQuickInsertBar(tagRoot);
                tagInput.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    const value = e.target.value;
                    debounceTimer = setTimeout(() => {
                        loadTags(value.trim());
                        loadWildcards(value.trim());
                    }, 250);
                });
            }
        }

        // Wildcard search: only filters wildcards.
        if (wcRoot) {
            const wcInput = wcRoot.querySelector('input') || wcRoot.querySelector('textarea');
            if (wcInput) {
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
        if (root.querySelector('.pc-tag-quickbar')) return;

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

        // Put right under the search input (Tag Dictionary area)
        root.appendChild(label);
        root.appendChild(bar);
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

    function setupPathSelector(paths) {
        const labelEl = document.getElementById('pc_tag_path_label');
        if (!labelEl) return;

        allPaths = (paths || []).slice();

        function labelForPath(p) {
            const sec = p.section || '';
            const cat = p.category || '';
            const grp = p.group || '';
            const parts = [sec, cat, grp].filter(Boolean);
            return parts.join(' / ') || '(未分類)';
        }

        // Build section/category/group sets from full path list
        const sections = new Map(); // sec -> Map(cat -> Set(grp))
        allPaths.forEach(p => {
            const sec = (p.section || '').trim();
            const cat = (p.category || '').trim();
            const grp = (p.group || '').trim();
            if (!sections.has(sec)) sections.set(sec, new Map());
            const cats = sections.get(sec);
            if (!cats.has(cat)) cats.set(cat, new Set());
            cats.get(cat).add(grp);
        });

        let selectedSection = '';
        let selectedCategory = '';
        let selectedGroup = '';

        labelEl.innerHTML = '';
        const wrapper = document.createElement('div');
        wrapper.className = 'pc-tag-path-grid';

        const hint = document.createElement('div');
        hint.className = 'pc-tag-path-hint';
        hint.textContent = 'パス絞り込み（セクション → カテゴリ → グループ）';

        const listHost = document.createElement('div');
        listHost.className = 'pc-tag-path-matches';

        function makeSearchDropdown(title) {
            const host = document.createElement('div');
            host.className = 'pc-tag-dd';

            const lbl = document.createElement('div');
            lbl.className = 'pc-tag-dd-label';
            lbl.textContent = title;

            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'pc-tag-dd-input';
            input.placeholder = '(すべて)';

            const list = document.createElement('div');
            list.className = 'pc-tag-dd-list';
            list.style.display = 'none';

            host.appendChild(lbl);
            host.appendChild(input);
            host.appendChild(list);

            function openList() { list.style.display = 'block'; }
            function closeListSoon() { setTimeout(() => { list.style.display = 'none'; }, 150); }

            input.addEventListener('focus', openList);
            input.addEventListener('blur', closeListSoon);

            return { host, input, list, openList };
        }

        const secDD = makeSearchDropdown('セクション');
        const catDD = makeSearchDropdown('カテゴリ');
        const grpDD = makeSearchDropdown('グループ');

        function uniqSorted(arr) {
            return Array.from(new Set(arr)).sort((a, b) => (a || '').localeCompare(b || '', 'ja'));
        }

        function renderDD(dd, items, onPick, selectedValue) {
            let raw = (dd.input.value || '').trim();
            // Treat placeholder display as "no filter"
            if (raw === '(すべて)') raw = '';
            // When just showing the selected value, don't use it as a filter
            if (selectedValue && raw === selectedValue) {
                raw = '';
            }
            const q = raw.toLowerCase();
            let filtered = items;
            if (q) filtered = items.filter(x => (x || '').toLowerCase().includes(q));

            const maxItems = 80;
            if (filtered.length > maxItems) filtered = filtered.slice(0, maxItems);

            let html = `<button type="button" class="pc-tag-dd-item" data-value="">(すべて)</button>`;
            filtered.forEach(v => {
                const label = v || '(未分類)';
                html += `<button type="button" class="pc-tag-dd-item" data-value="${escapeHtml(v)}">${escapeHtml(label)}</button>`;
            });
            dd.list.innerHTML = html;

            dd.list.querySelectorAll('.pc-tag-dd-item').forEach(btn => {
                btn.addEventListener('click', () => {
                    const v = btn.dataset.value ?? '';
                    onPick(v);
                    dd.list.style.display = 'none';
                });
            });
        }

        function updateMatchesAndLoad() {
            // Apply partial filters directly (section only / section+category / full)
            currentSection = selectedSection ? selectedSection : null;
            currentCategory = selectedCategory ? selectedCategory : null;
            currentGroup = selectedGroup ? selectedGroup : null;

            const hasAnySelection = !!(selectedSection || selectedCategory || selectedGroup);

            // Render matching paths list (click to set exact triple)
            const matches = allPaths.filter(p => {
                const sec = (p.section || '').trim();
                const cat = (p.category || '').trim();
                const grp = (p.group || '').trim();
                if (selectedSection && sec !== selectedSection) return false;
                if (selectedCategory && cat !== selectedCategory) return false;
                if (selectedGroup && grp !== selectedGroup) return false;
                return true;
            });

            // Initial state: keep it clean (show nothing until user selects something)
            if (!hasAnySelection) {
                listHost.innerHTML = '';
                const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
                const q = qInput ? qInput.value : '';
                loadTags(q || '');
                return;
            }

            const shown = matches.slice(0, 120);
            listHost.innerHTML = `
                <div class="pc-tag-path-matches-head">候補: ${matches.length}件</div>
                <div class="pc-tag-path-matches-list">
                    ${shown.map(p => {
                        const label = labelForPath(p);
                        const idx = matches.indexOf(p);
                        // store index into the filtered matches list (stable for this render)
                        return `<button type="button" class="pc-tag-path-match" data-match-index="${idx}">${escapeHtml(label)}</button>`;
                    }).join('')}
                    ${matches.length > shown.length ? `<div class="pc-tag-path-more">… ${matches.length - shown.length}件省略（さらに絞り込み）</div>` : ''}
                </div>
            `;

            listHost.querySelectorAll('.pc-tag-path-match').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.matchIndex || '', 10);
                    if (isNaN(idx) || idx < 0 || idx >= matches.length) return;
                    const p = matches[idx];
                    if (!p) return;

                    selectedSection = (p.section || '').trim();
                    selectedCategory = (p.category || '').trim();
                    selectedGroup = (p.group || '').trim();

                    // reflect inputs
                    secDD.input.value = selectedSection || '(すべて)';
                    catDD.input.value = selectedCategory || '(すべて)';
                    grpDD.input.value = selectedGroup || '(すべて)';

                    // rebuild dependent dropdowns + refresh matches/tag list
                    refreshDropdowns();
                    updateMatchesAndLoad();
                });
            });

            const qInput = document.querySelector('#pc_tag_search input, #pc_tag_search textarea');
            const q = qInput ? qInput.value : '';
            loadTags(q || '');
        }

        function refreshDropdowns() {
            function setDisplay(dd, v) {
                dd.input.value = (v && String(v).trim()) ? String(v).trim() : '(すべて)';
            }

            // sections
            const secItems = uniqSorted(Array.from(sections.keys()));
            renderDD(secDD, secItems, (v) => {
                selectedSection = (v || '').trim();
                if (!selectedSection) {
                    selectedCategory = '';
                    selectedGroup = '';
                } else {
                    // reset dependent selections when section changes
                    selectedCategory = '';
                    selectedGroup = '';
                }
                setDisplay(secDD, selectedSection);
                setDisplay(catDD, selectedCategory);
                setDisplay(grpDD, selectedGroup);
                updateMatchesAndLoad();
                refreshDropdowns();
            }, selectedSection);

            // categories depend on section
            let catItems = [];
            if (selectedSection && sections.has(selectedSection)) {
                catItems = uniqSorted(Array.from(sections.get(selectedSection).keys()));
            } else {
                // when section not selected, show all categories across sections (still searchable)
                const allCats = [];
                sections.forEach(cats => cats.forEach((_g, cat) => allCats.push(cat)));
                catItems = uniqSorted(allCats);
            }
            renderDD(catDD, catItems, (v) => {
                selectedCategory = (v || '').trim();
                selectedGroup = '';
                setDisplay(catDD, selectedCategory);
                setDisplay(grpDD, selectedGroup);
                updateMatchesAndLoad();
                refreshDropdowns();
            }, selectedCategory);

            // groups depend on section+category (best), else broaden
            let grpItems = [];
            if (selectedSection && sections.has(selectedSection)) {
                const cats = sections.get(selectedSection);
                if (selectedCategory && cats.has(selectedCategory)) {
                    grpItems = uniqSorted(Array.from(cats.get(selectedCategory)));
                } else if (!selectedCategory) {
                    const allGrps = [];
                    cats.forEach(gs => gs.forEach(g => allGrps.push(g)));
                    grpItems = uniqSorted(allGrps);
                }
            } else if (selectedCategory) {
                const allGrps = [];
                sections.forEach(cats => {
                    if (cats.has(selectedCategory)) cats.get(selectedCategory).forEach(g => allGrps.push(g));
                });
                grpItems = uniqSorted(allGrps);
            } else {
                const allGrps = [];
                sections.forEach(cats => cats.forEach(gs => gs.forEach(g => allGrps.push(g))));
                grpItems = uniqSorted(allGrps);
            }

            renderDD(grpDD, grpItems, (v) => {
                selectedGroup = (v || '').trim();
                setDisplay(grpDD, selectedGroup);
                updateMatchesAndLoad();
                refreshDropdowns();
            }, selectedGroup);
        }

        // typing filters the suggestion list live
        secDD.input.addEventListener('input', () => refreshDropdowns());
        catDD.input.addEventListener('input', () => refreshDropdowns());
        grpDD.input.addEventListener('input', () => refreshDropdowns());

        wrapper.appendChild(hint);
        wrapper.appendChild(secDD.host);
        wrapper.appendChild(catDD.host);
        wrapper.appendChild(grpDD.host);
        labelEl.appendChild(wrapper);
        labelEl.appendChild(listHost);

        refreshDropdowns();
        updateMatchesAndLoad();
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
        reload: () => loadTags('')
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1500));
    } else {
        setTimeout(init, 1500);
    }

})();

