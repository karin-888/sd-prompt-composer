/**
 * Tag Dictionary Panel
 * Uses /prompt-composer/api/tags to provide a searchable list
 * of prompt tags with Japanese translations.
 */
(function() {
    'use strict';

    let currentItems = [];
    let debounceTimer = null;
    let currentSection = null;
    let currentCategory = null;
    let currentGroup = null;
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
            currentItems = data.items || [];
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
            wcHost = document.createElement('div');
            wcHost.id = 'pc_wildcards_container';
            wcHost.className = 'pc-wc-container';
            // insert below the tag list area
            if (container.parentElement) {
                container.parentElement.insertBefore(wcHost, container.nextSibling);
            }
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
                const blocks = window.PromptComposer.blocks || [];

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
                            <button class="pc-tag-row" data-tag="${tag}">
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

                const blocks = window.PromptComposer.blocks || [];

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
                    isTrigger: false
                });
            });
        });
    }

    function setupSearch() {
        const root = document.getElementById('pc_tag_search');
        if (!root) return;
        const input = root.querySelector('input') || root.querySelector('textarea');
        if (!input) return;

        ensureQuickInsertBar(root);

        input.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            const value = e.target.value;
            debounceTimer = setTimeout(() => {
                loadTags(value.trim());
                loadWildcards(value.trim());
            }, 250);
        });
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
        const blocks = window.PromptComposer.blocks || [];
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

        // Build a simple select element like the folder dropdown behavior
        const select = document.createElement('select');
        select.className = 'pc-tag-path-select';

        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = '(すべて)';
        select.appendChild(allOption);

        paths.forEach(p => {
            const sec = p.section || '';
            const cat = p.category || '';
            const grp = p.group || '';
            const parts = [sec, cat, grp].filter(Boolean);
            const opt = document.createElement('option');
            opt.value = JSON.stringify(p);
            opt.textContent = parts.join(' / ');
            select.appendChild(opt);
        });

        select.addEventListener('change', (e) => {
            const v = e.target.value;
            if (!v) {
                currentSection = currentCategory = currentGroup = null;
            } else {
                try {
                    const p = JSON.parse(v);
                    currentSection = p.section || null;
                    currentCategory = p.category || null;
                    currentGroup = p.group || null;
                } catch {
                    currentSection = currentCategory = currentGroup = null;
                }
            }
            loadTags(document.querySelector('#pc_tag_search input, #pc_tag_search textarea')?.value || '');
        });

        labelEl.innerHTML = '';
        labelEl.appendChild(select);
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

