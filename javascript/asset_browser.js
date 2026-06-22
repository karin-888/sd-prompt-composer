/**
 * Asset Browser - LoRA/Embedding card browser with search and filtering
 * Fetches assets from the API and renders image cards.
 */
(function() {
    'use strict';

    // State
    let displayedAssets = [];
    let currentOffset = 0;
    let currentSearch = '';
    let currentTypeFilter = 'lora';
    let currentSubfolder = '';
    let currentSpecialFilter = ''; // 'favorites'
    let isLoading = false;
    let rescanInProgress = false;
    const PAGE_SIZE = 50;
    const MAX_DOM_CARDS = 250; // safety cap for DOM size
    let imageObserver = null;
    let infiniteScrollObserver = null;

    // ===== Initialization =====
    function init() {
        const gallery = document.getElementById('pc_asset_cards');
        if (!gallery) {
            setTimeout(init, 500);
            return;
        }

        setupEventListeners();
        setupObservers();
        loadAssets();
        loadSubfolders();

        if (typeof onOptionsChanged === 'function') {
            onOptionsChanged(function () {
                markActiveCheckpointCards();
            });
        }
        
        console.log('[Prompt Composer] Asset Browser initialized');
    }

    // ===== Data Loading =====
    async function loadAssets(append = false) {
        if (isLoading) return;
        isLoading = true;

        const gallery = document.getElementById('pc_asset_cards');
        if (!gallery) {
            isLoading = false;
            return;
        }

        if (!append) {
            gallery.innerHTML = '<div class="pc-loading">読み込み中...</div>';
            currentOffset = 0;
        }

        try {
            let url = `/prompt-composer/api/assets?limit=${PAGE_SIZE}&offset=${currentOffset}`;
            if (currentTypeFilter) url += `&type=${currentTypeFilter}`;
            if (currentSpecialFilter) url += `&special=${currentSpecialFilter}`;
            if (currentSubfolder) url += `&subfolder=${encodeURIComponent(currentSubfolder)}`;
            if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;

            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            let data = await resp.json();

            // Sort assets by displayName / name for stable ordering
            let filteredAssets = (data.assets || []).slice().sort((a, b) => {
                const aName = (a.displayName || a.name || '').toLowerCase();
                const bName = (b.displayName || b.name || '').toLowerCase();
                if (aName < bName) return -1;
                if (aName > bName) return 1;
                return 0;
            });

            if (!append) {
                displayedAssets = filteredAssets;
            } else {
                displayedAssets = displayedAssets.concat(filteredAssets);
            }

            // cap in-memory list just in case, though main limit is DOM size
            if (displayedAssets.length > MAX_DOM_CARDS * 2) {
                displayedAssets = displayedAssets.slice(-MAX_DOM_CARDS * 2);
            }

            renderAssetCards(displayedAssets, data.total, append);
            currentOffset = displayedAssets.length;
            markActiveCheckpointCards();
            if (!append) {
                loadSubfolders(currentSubfolder || '(すべて)');
            }

            // Show/hide load more button
            const loadMoreBtn = document.getElementById('pc_asset_load_more');
            if (loadMoreBtn) {
                const parent = loadMoreBtn.closest('.gradio-button, button');
                const actual = parent || loadMoreBtn;
                if (displayedAssets.length >= data.total) {
                    actual.style.display = 'none';
                } else {
                    actual.style.display = '';
                }
            }

        } catch (err) {
            console.error('[Prompt Composer] Failed to load assets:', err);
            if (!append) {
                gallery.innerHTML = '<div class="pc-error">アセットの読み込みに失敗しました</div>';
            }
        } finally {
            isLoading = false;
        }
    }

    function setSubfolderDropdownValue(root, value, options = {}) {
        if (!root) return;
        const next = value || '(すべて)';
        const input = root.querySelector('input');
        const selected = root.querySelector('span.single-select, .selected');

        if (input) {
            input.value = next;
            if (typeof updateInput === 'function') {
                try { updateInput(input); } catch (_) { /* ignore */ }
            }
            if (!options.silent) {
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
        if (selected) {
            selected.textContent = next;
        }

        root.querySelectorAll('ul.options li.item, ul li.item, ul.options li, ul li').forEach((item) => {
            const text = (item.textContent || '').replace(/\s+/g, ' ').trim();
            item.classList.toggle('selected', text === next);
        });
    }

    function populateSubfolderDropdown(subfolders, selectedValue) {
        const root = document.getElementById('pc_asset_subfolder');
        if (!root) return false;

        const choices = ['(すべて)'].concat((subfolders || []).filter(Boolean));
        const value = selectedValue || '(すべて)';
        let optionsList = root.querySelector('ul.options, ul');

        if (!optionsList) {
            const wrap = root.querySelector('.wrap-inner, .wrap');
            if (!wrap) return false;
            optionsList = document.createElement('ul');
            optionsList.className = 'options';
            wrap.appendChild(optionsList);
        }

        optionsList.innerHTML = '';
        choices.forEach((choice) => {
            const item = document.createElement('li');
            item.className = 'item' + (choice === value ? ' selected' : '');
            item.textContent = choice;
            item.addEventListener('mousedown', (event) => {
                event.preventDefault();
                currentSubfolder = choice === '(すべて)' ? '' : choice;
                setSubfolderDropdownValue(root, choice);
                loadAssets();
            });
            optionsList.appendChild(item);
        });

        setSubfolderDropdownValue(root, value, { silent: true });
        window._pcSubfolders = subfolders || [];
        return true;
    }

    async function loadSubfolders(selectedValue) {
        try {
            let url = '/prompt-composer/api/assets/subfolders';
            if (currentTypeFilter) {
                url += `?type=${encodeURIComponent(currentTypeFilter)}`;
            }

            const resp = await fetch(url);
            if (!resp.ok) return;
            const data = await resp.json();
            const keepValue = selectedValue || currentSubfolder || '(すべて)';
            populateSubfolderDropdown(data.subfolders, keepValue === '' ? '(すべて)' : keepValue);
        } catch (err) {
            console.warn('[Prompt Composer] Failed to load subfolders:', err);
        }
    }

    // ===== Rendering =====
    function renderAssetCards(assets, total, append = false) {
        const gallery = document.getElementById('pc_asset_cards');
        if (!gallery) return;

        if (!append) {
            if (assets.length === 0) {
                gallery.innerHTML = '<div class="pc-empty">アセットが見つかりません</div>';
                return;
            }

            let html = `<div class="pc-asset-count">${total} 件中 ${assets.length} 件表示</div>`;
            html += '<div class="pc-asset-grid"></div><div id="pc_asset_sentinal" class="pc-asset-sentinel"></div>';
            gallery.innerHTML = html;
        }

        const grid = gallery.querySelector('.pc-asset-grid');
        if (!grid) return;

        // Remove oldest cards if DOM grows too big
        const existingCards = Array.from(grid.querySelectorAll('.pc-asset-card'));
        if (existingCards.length > MAX_DOM_CARDS) {
            const toRemove = existingCards.length - MAX_DOM_CARDS;
            for (let i = 0; i < toRemove; i++) {
                existingCards[i].remove();
            }
        }

        const fragment = document.createDocumentFragment();

        assets.slice(existingCards.length).forEach(asset => {
            const previewSrc = asset.previewUrl || '';
            const triggerStr = (asset.triggerWords || []).join(', ');
            const isCheckpoint = asset.type === 'checkpoint';
            const typeClass = isCheckpoint ? 'pc-type-checkpoint'
                : (asset.type === 'lora' ? 'pc-type-lora' : 'pc-type-embedding');
            const typeBadge = isCheckpoint ? 'CKPT'
                : (asset.type === 'lora' ? 'LoRA' : 'Emb');
            const weightStr = asset.defaultWeight ? `w:${asset.defaultWeight}` : '';
            const subfolder = asset.subfolder || '';
            const favClass = asset.isFavorite ? 'pc-fav-active' : '';
            const baseName = asset.name || asset.displayName || '';
            const civitaiUrl = asset.civitaiUrl
                || `https://civitai.com/search/models?query=${encodeURIComponent(baseName)}`;
            
            let blockHint = '';
            if (asset.preferredBlock) {
                const blockNames = {
                    'quality': '🏆 品質', 'subject': '🎯 主題', 'character': '👤 キャラ',
                    'appearance': '✨ 外見', 'outfit': '👗 衣装', 'expression': '😊 表情',
                    'composition': '📐 構図', 'background': '🌄 背景', 'lighting': '💡 光',
                    'style': '🎨 画風', 'lora': '🔧 LoRA', 'embedding': '📦 Embedding'
                };
                const bName = blockNames[asset.preferredBlock] || asset.preferredBlock;
                blockHint = `<div class="pc-asset-block-hint" title="挿入先: ${bName}">→ ${bName}</div>`;
            }
            
            const wrapper = document.createElement('div');
            wrapper.className = 'pc-asset-card' + (isCheckpoint ? ' pc-asset-card-checkpoint' : '');
            wrapper.dataset.assetId = asset.id;
            wrapper.dataset.assetType = asset.type || '';
            if (isCheckpoint && asset.checkpointTitle) {
                wrapper.dataset.checkpointTitle = asset.checkpointTitle;
            }
            wrapper.title = isCheckpoint
                ? `${escapeHtml(asset.displayName || asset.name)}（クリックでチェックポイントを切り替え）`
                : escapeHtml(asset.displayName);

            wrapper.innerHTML = `
                    ${isCheckpoint ? '' : `<button class="pc-asset-fav-btn ${favClass}" data-asset-id="${asset.id}" title="お気に入り">⭐</button>`}
                    ${isCheckpoint ? '' : `<button class="pc-asset-remove-btn" data-asset-id="${asset.id}" title="削除（フォルダから）">×</button>`}
                    <div class="pc-asset-preview">
                        ${previewSrc 
                            ? `<img loading="lazy" data-src="${previewSrc}" alt="${escapeHtml(asset.name)}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
                               <div class="pc-asset-no-preview" style="display:none">${isCheckpoint ? '🧠' : '📄'}</div>`
                            : `<div class="pc-asset-no-preview">${isCheckpoint ? '🧠' : '📄'}</div>`
                        }
                        <span class="pc-asset-type-badge ${typeClass}">${typeBadge}</span>
                        ${isCheckpoint ? '' : `<button class="pc-asset-civitai-icon" data-civitai-url="${escapeHtml(civitaiUrl)}" title="Civitaiで開く">🌐</button>`}
                    </div>
                    <div class="pc-asset-info">
                        <div class="pc-asset-name">${escapeHtml(asset.displayName || asset.name)}</div>
                        ${subfolder ? `<div class="pc-asset-subfolder">${escapeHtml(subfolder)}</div>` : ''}
                        ${triggerStr ? `<div class="pc-asset-trigger" title="${escapeHtml(triggerStr)}">🏷️ ${escapeHtml(triggerStr)}</div>` : ''}
                        ${weightStr ? `<div class="pc-asset-weight">${weightStr}</div>` : ''}
                        ${isCheckpoint ? '<div class="pc-asset-checkpoint-hint">クリックで反映</div>' : ''}
                    </div>
                    ${blockHint}
            `;
            fragment.appendChild(wrapper);
        });

        grid.appendChild(fragment);

        // Attach handlers only for new cards
        grid.querySelectorAll('.pc-asset-card').forEach(card => {
            if (!card.dataset._pcHandlersAttached) {
                card.addEventListener('click', onAssetCardClick);
                const favBtn = card.querySelector('.pc-asset-fav-btn');
                if (favBtn) favBtn.addEventListener('click', onFavoriteToggle);
                const rmBtn = card.querySelector('.pc-asset-remove-btn');
                if (rmBtn) rmBtn.addEventListener('click', onAssetRemoveClick);
                const civIcon = card.querySelector('.pc-asset-civitai-icon');
                if (civIcon) civIcon.addEventListener('click', onCivitaiOpen);
                card.dataset._pcHandlersAttached = '1';
            }
        });

        // Lazy-load images
        if (imageObserver) {
            grid.querySelectorAll('img[data-src]').forEach(img => {
                if (!img.dataset._pcObserved) {
                    imageObserver.observe(img);
                    img.dataset._pcObserved = '1';
                }
            });
        }

        // (re)attach infinite scroll observer
        const sentinel = gallery.querySelector('#pc_asset_sentinal');
        if (sentinel && infiniteScrollObserver) {
            infiniteScrollObserver.observe(sentinel);
        }
    }

    // ===== Event Handlers =====
    function readSubfolderDropdownValue(subfolderEl) {
        if (!subfolderEl) return '';
        const input = subfolderEl.querySelector('input');
        let rawVal = (input && input.value ? input.value : '').trim();
        if (!rawVal) {
            const selected = subfolderEl.querySelector('span.single-select, .selected');
            if (selected) {
                rawVal = (selected.textContent || '').replace(/\s+/g, ' ').trim();
            }
        }
        return rawVal === '(すべて)' ? '' : rawVal;
    }

    function setupEventListeners() {
        // Search input
        const searchEl = document.getElementById('pc_asset_search');
        if (searchEl) {
            const input = searchEl.querySelector('input') || searchEl.querySelector('textarea');
            if (input) {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        currentSearch = e.target.value.trim();
                        loadAssets();
                    }, 300);
                });
            }
        }

        // Type filter radio
        const typeFilter = document.getElementById('pc_asset_type_filter');
        if (typeFilter) {
            typeFilter.addEventListener('change', (e) => {
                const val = e.target.value;
                if (!val) return;

                console.log('[Prompt Composer] Type filter changed to:', val);

                if (val === 'Checkpoint') {
                    currentTypeFilter = 'checkpoint';
                    currentSpecialFilter = '';
                    currentSubfolder = '';
                    const sfInput = document.querySelector('#pc_asset_subfolder input');
                    if (sfInput) sfInput.value = '';
                } else if (val === 'LoRA') {
                    currentTypeFilter = 'lora';
                    currentSpecialFilter = '';
                    currentSubfolder = '';
                    const sfInput = document.querySelector('#pc_asset_subfolder input');
                    if (sfInput) sfInput.value = '';
                } else if (val === 'Embedding') {
                    currentTypeFilter = 'embedding';
                    currentSpecialFilter = '';
                    currentSubfolder = '';
                    const sfInput = document.querySelector('#pc_asset_subfolder input');
                    if (sfInput) sfInput.value = '';
                } else if (val === 'Favorites' || val === 'お気に入り') {
                    currentTypeFilter = '';
                    currentSpecialFilter = 'favorites';
                    // Clear subfolder when specifically looking at favorites
                    currentSubfolder = '';
                    const sfInput = document.querySelector('#pc_asset_subfolder input');
                    if (sfInput) sfInput.value = '(すべて)';
                }

                loadSubfolders('(すべて)');
                loadAssets();
            });
        }

        // Subfolder filter
        const subfolderEl = document.getElementById('pc_asset_subfolder');
        if (subfolderEl) {
            const input = subfolderEl.querySelector('input');
            if (input) {
                const handleSubfolderChange = () => {
                    // Use timeout because Gradio might not have updated the input value yet
                    setTimeout(() => {
                        const newVal = readSubfolderDropdownValue(subfolderEl);
                        if (currentSubfolder !== newVal) {
                            console.log('[Prompt Composer] Subfolder changed to:', newVal || '(すべて)');
                            currentSubfolder = newVal;

                            // If a subfolder is selected, we usually want to see everything in it,
                            // so clear the Favorites special filter
                            if (currentSpecialFilter) {
                                currentSpecialFilter = '';
                            }

                            loadAssets();
                        }
                    }, 100);
                };
                input.addEventListener('change', handleSubfolderChange);
                input.addEventListener('blur', handleSubfolderChange);
                // Listen to Gradio's specific input event if possible
                input.addEventListener('input', handleSubfolderChange);
            }
        }

        // Rescan button
        const rescanBtn = document.getElementById('pc_asset_rescan');
        if (rescanBtn) {
            rescanBtn.addEventListener('click', async () => {
                if (rescanInProgress) return;
                rescanInProgress = true;
                const gallery = document.getElementById('pc_asset_cards');
                const keepSubfolder = currentSubfolder || '(すべて)';
                if (gallery) gallery.innerHTML = '<div class="pc-loading">再スキャン中...</div>';

                try {
                    const resp = await fetch('/prompt-composer/api/assets/rescan');
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    await loadSubfolders(keepSubfolder);
                    rescanInProgress = false;
                    await loadAssets(false);
                } catch (err) {
                    console.error('[Prompt Composer] Rescan failed:', err);
                    rescanInProgress = false;
                    if (gallery) {
                        gallery.innerHTML = '<div class="pc-error">再スキャンに失敗しました</div>';
                    }
                }
            });
        }

        // Load more button
        const loadMoreBtn = document.getElementById('pc_asset_load_more');
        if (loadMoreBtn) {
            loadMoreBtn.addEventListener('click', () => {
                loadAssets(true);
            });
        }
    }

    function setupObservers() {
        // Image lazy loader
        imageObserver = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                const img = entry.target;
                const src = img.getAttribute('data-src');
                if (src) {
                    img.src = src;
                    img.removeAttribute('data-src');
                }
                obs.unobserve(img);
            });
        }, {
            root: document.querySelector('#pc_asset_cards'),
            rootMargin: '200px',
            threshold: 0.01
        });

        // Infinite scroll sentinel
        infiniteScrollObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                // Auto-load more when user scrolls near bottom
                loadAssets(true);
            });
        }, {
            root: document.querySelector('#pc_asset_cards'),
            rootMargin: '200px',
            threshold: 0.01
        });

        const gallery = document.getElementById('pc_asset_cards');
        if (gallery) {
            const sentinel = gallery.querySelector('#pc_asset_sentinal');
            if (sentinel) {
                infiniteScrollObserver.observe(sentinel);
            }
        }
    }

    function getCurrentCheckpointTitle() {
        try {
            if (typeof opts !== 'undefined' && opts.sd_model_checkpoint) {
                return String(opts.sd_model_checkpoint);
            }
        } catch (_) { /* ignore */ }
        return '';
    }

    function markActiveCheckpointCards() {
        const current = getCurrentCheckpointTitle();
        document.querySelectorAll('#pc_asset_cards .pc-asset-card-checkpoint').forEach(function (card) {
            const title = card.dataset.checkpointTitle || '';
            card.classList.toggle('pc-asset-checkpoint-active', !!title && title === current);
        });
    }

    function applyCheckpoint(asset, card) {
        const title = asset.checkpointTitle || asset.title;
        if (!title) return;

        if (typeof selectCheckpoint === 'function') {
            selectCheckpoint(title);
        } else {
            try {
                const root = (typeof gradioApp === 'function') ? gradioApp() : document;
                const input = root.querySelector('#setting_sd_model_checkpoint input');
                if (input) {
                    input.value = title;
                    if (typeof updateInput === 'function') updateInput(input);
                }
                const btn = root.getElementById('change_checkpoint');
                if (btn) btn.click();
            } catch (err) {
                console.warn('[Prompt Composer] Failed to apply checkpoint:', err);
                alert('チェックポイントの切り替えに失敗しました');
                return;
            }
        }

        document.querySelectorAll('#pc_asset_cards .pc-asset-card-checkpoint').forEach(function (el) {
            el.classList.remove('pc-asset-checkpoint-active', 'pc-asset-inserted');
        });
        if (card) {
            card.classList.add('pc-asset-checkpoint-active', 'pc-asset-inserted');
            setTimeout(function () { card.classList.remove('pc-asset-inserted'); }, 800);
        }
        setTimeout(markActiveCheckpointCards, 1200);
    }

    async function onAssetCardClick(e) {
        // Ignore if clicking the favorite button
        if (e.target.closest('.pc-asset-fav-btn')) return;
        if (e.target.closest('.pc-asset-remove-btn')) return;

        const card = e.target.closest('.pc-asset-card');
        if (!card) return;

        const assetId = card.dataset.assetId;
        const asset = displayedAssets.find(a => a.id === assetId);
        if (!asset) return;

        if (asset.type === 'checkpoint') {
            applyCheckpoint(asset, card);
            return;
        }
        
        if (window.PromptComposer) {
            window.PromptComposer.insertAsset(asset);
            
            // Record usage
            try {
                fetch(`/prompt-composer/api/assets/${assetId}/use`, { method: 'POST' });
                asset.usageCount = (asset.usageCount || 0) + 1;
            } catch (err) {}
            
            // Visual feedback
            card.classList.add('pc-asset-inserted');
            setTimeout(() => card.classList.remove('pc-asset-inserted'), 600);
        }
    }

    async function onAssetRemoveClick(e) {
        e.stopPropagation(); // Prevent card insert
        const btn = e.currentTarget;
        const assetId = btn && btn.dataset ? btn.dataset.assetId : null;
        if (!assetId) return;

        const asset = displayedAssets.find(a => a.id === assetId);
        const name = (asset && (asset.displayName || asset.name)) ? String(asset.displayName || asset.name) : assetId;

        if (!confirm(`「${name}」を削除しますか？（フォルダから削除、元に戻せません）`)) return;

        try {
            btn.disabled = true;
            const delResp = await fetch(`/prompt-composer/api/assets/${assetId}`, { method: 'DELETE' });
            if (!delResp.ok) {
                const body = await delResp.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${delResp.status}`);
            }

            // Refresh index + UI
            await fetch('/prompt-composer/api/assets/rescan', { method: 'GET' });
            await loadAssets(false);
        } catch (err) {
            console.error('[Prompt Composer] Failed to delete asset:', err);
            alert(`削除に失敗しました: ${err && err.message ? err.message : err}`);
        } finally {
            try { btn.disabled = false; } catch (_) {}
        }
    }

    async function onFavoriteToggle(e) {
        e.stopPropagation(); // Prevent card click
        const btn = e.currentTarget;
        const assetId = btn.dataset.assetId;
        const asset = displayedAssets.find(a => a.id === assetId);
        
        if (!asset) return;
        
        const isFav = !asset.isFavorite; // Toggle
        asset.isFavorite = isFav;
        
        // Immediate visual update
        if (isFav) {
            btn.classList.add('pc-fav-active');
        } else {
            btn.classList.remove('pc-fav-active');
        }
        
        // Update server
        try {
            if (isFav) {
                await fetch(`/prompt-composer/api/favorites/${assetId}`, { method: 'POST' });
            } else {
                await fetch(`/prompt-composer/api/favorites/${assetId}`, { method: 'DELETE' });
            }
        } catch (err) {
            console.error('[Prompt Composer] Failed to toggle favorite:', err);
            // Revert on failure
            asset.isFavorite = !isFav;
            if (asset.isFavorite) btn.classList.add('pc-fav-active');
            else btn.classList.remove('pc-fav-active');
        }
    }

    function onCivitaiOpen(e) {
        e.stopPropagation(); // Prevent card click
        const btn = e.currentTarget;
        const url = btn.dataset.civitaiUrl;
        if (!url) return;
        try {
            window.open(url, '_blank');
        } catch (err) {
            console.warn('[Prompt Composer] Failed to open Civitai URL:', err);
        }
    }

    // ===== Utility =====
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ===== Public API =====
    window.AssetBrowser = {
        init,
        loadAssets,
        refresh: () => loadAssets()
    };

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 1500));
    } else {
        setTimeout(init, 1500);
    }

    // Gradio load observer (body may not exist yet at script eval time — use fallback + retry)
    const observer = new MutationObserver((mutations, obs) => {
        if (document.getElementById('pc_asset_cards')) {
            obs.disconnect();
            setTimeout(init, 500);
        }
    });
    function startAssetObserver() {
        const target = (typeof document.body !== 'undefined' && document.body)
            ? document.body
            : document.documentElement;
        if (!(target instanceof Node)) {
            requestAnimationFrame(startAssetObserver);
            return;
        }
        try {
            observer.observe(target, { childList: true, subtree: true });
        } catch (_) {
            requestAnimationFrame(startAssetObserver);
        }
    }
    startAssetObserver();

})();
