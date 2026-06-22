/**
 * Prompt Sync - Apply prompts to txt2img/img2img and clipboard
 */
(function() {
    'use strict';

    function appRoot() {
        // In A1111/Forge, UI lives inside Gradio iframe; gradioApp() returns its document.
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) {}
        return document;
    }

    function getButtonEl(elemId) {
        const root = appRoot().getElementById(elemId);
        if (!root) return null;
        // Gradio often assigns elem_id to a wrapper; the real clickable is a nested <button>
        return root.tagName === 'BUTTON' ? root : (root.querySelector('button') || root);
    }

    let _syncLogged = false;
    let _galleryObserver = null;
    let _pcProgressTimer = null;
    let _pcLivePreviewId = -1;
    let _pcProgressWasActive = false;
    let _pcForeverProgressSession = false;
    let _pcProgressTarget = 'txt2img';
    let _pcGenerateForeverActive = false;

    function setGenerateForeverActive(active) {
        _pcGenerateForeverActive = !!active;
    }

    function resetGenerateForeverLoop() {
        clearInterval(window.generateOnRepeatInterval);
        window.generateOnRepeatInterval = null;
        _pcGenerateForeverActive = false;
    }

    function resetGenerateForeverState() {
        resetGenerateForeverLoop();
        _pcForeverProgressSession = false;
    }

    function isTxt2imgGenerationInProgress() {
        const interruptEl = getInterruptEl('txt2img');
        if (interruptEl && interruptEl.offsetParent) return true;
        try {
            if (typeof localGet === 'function') {
                const taskId = localGet('txt2img_task_id', null);
                if (taskId) return true;
            }
        } catch (_) { /* ignore */ }
        return false;
    }

    function init() {
        resetGenerateForeverState();
        stopPcProgressWatch();
        setupButtons();
        setupGeneratePreview();
        if (!_syncLogged) {
            _syncLogged = true;
            console.log('[Prompt Composer] Prompt Sync initialized');
        }
    }

    function getGenerateButton(target) {
        const root = appRoot();
        return root.querySelector(`#${target}_generate button`)
            || root.querySelector(`#${target}_generate`);
    }

    function getGalleryImages(target) {
        const gallery = appRoot().querySelector(`#${target}_gallery`);
        if (!gallery) return [];
        return Array.from(gallery.querySelectorAll('img')).filter(img => img.src && !img.src.includes('svg'));
    }

    function formatTime(secs) {
        const pad2 = (x) => (x < 10 ? '0' + x : '' + x);
        if (secs > 3600) {
            return pad2(Math.floor(secs / 3600)) + ':' + pad2(Math.floor(secs / 60) % 60) + ':' + pad2(Math.floor(secs) % 60);
        }
        if (secs > 60) {
            return pad2(Math.floor(secs / 60)) + ':' + pad2(Math.floor(secs) % 60);
        }
        return Math.floor(secs) + 's';
    }

    function getProgressRefreshMs() {
        try {
            if (typeof opts !== 'undefined' && opts.live_preview_refresh_period) {
                return Math.max(200, Number(opts.live_preview_refresh_period) || 500);
            }
        } catch (_) { /* ignore */ }
        return 500;
    }

    function fetchInternalProgress(payload) {
        return fetch('./internal/progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    /* 進捗表示は WebUI 標準の .progressDiv（Output タブ・ギャラリー上）のみ使用 */
    function showProgressUi() { /* no-op */ }

    function updateProgressUi() { /* no-op */ }

    let _pcPreviewLightboxBound = false;

    function ensurePcPreviewLightbox() {
        let box = document.getElementById('pc_preview_lightbox');
        if (box) return box;

        box = document.createElement('div');
        box.id = 'pc_preview_lightbox';
        box.className = 'pc-preview-lightbox';
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');
        box.setAttribute('aria-label', '生成画像プレビュー');
        box.innerHTML =
            '<div class="pc-preview-lightbox-backdrop" data-pc-lightbox-close="1"></div>' +
            '<div class="pc-preview-lightbox-panel">' +
            '<button type="button" class="pc-preview-lightbox-close" data-pc-lightbox-close="1" aria-label="閉じる">×</button>' +
            '<img class="pc-preview-lightbox-img" alt="生成プレビュー（拡大）" />' +
            '</div>';
        document.body.appendChild(box);

        if (!_pcPreviewLightboxBound) {
            _pcPreviewLightboxBound = true;
            box.addEventListener('click', (ev) => {
                if (ev.target.closest('[data-pc-lightbox-close]')) {
                    closePcPreviewLightbox();
                }
            });
            document.addEventListener('keydown', (ev) => {
                if (ev.key === 'Escape') closePcPreviewLightbox();
            });
        }
        return box;
    }

    function closePcPreviewLightbox() {
        const box = document.getElementById('pc_preview_lightbox');
        if (!box) return;
        box.style.display = 'none';
        box.classList.remove('pc-preview-lightbox-open');
        const img = box.querySelector('.pc-preview-lightbox-img');
        if (img) img.removeAttribute('src');
    }

    function tryOpenWebUiLightbox(src) {
        const root = appRoot();
        const lb = root.getElementById('lightboxModal');
        const modalImage = root.getElementById('modalImage');
        if (!lb || !modalImage || !src) return false;
        try {
            modalImage.src = src;
            modalImage.style.display = '';
            lb.style.display = 'flex';
            lb.focus();
            if (typeof updateModalImage === 'function') {
                updateModalImage();
            }
            return true;
        } catch (err) {
            console.warn('[Prompt Composer] WebUI lightbox failed:', err);
            return false;
        }
    }

    function openPreviewLightbox(src, e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        const url = (src || '').trim();
        if (!url) return;

        if (tryOpenWebUiLightbox(url)) return;

        const box = ensurePcPreviewLightbox();
        const img = box.querySelector('.pc-preview-lightbox-img');
        if (img) img.src = url;
        box.style.display = 'flex';
        box.classList.add('pc-preview-lightbox-open');
        const closeBtn = box.querySelector('.pc-preview-lightbox-close');
        if (closeBtn) closeBtn.focus();
    }

    function getProgressPreviewHost() {
        return appRoot().getElementById('pc_generate_live_preview')
            || appRoot().getElementById('pc_generate_preview');
    }

    function setPreviewImage(preview, src, isLive) {
        if (!preview || !src) return;
        if (preview.dataset.pcPreviewSrc === src && !isLive) return;
        preview.dataset.pcPreviewSrc = src;
        preview.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'pc-generate-preview-img' + (isLive ? ' pc-generate-preview-img-live' : '');
        img.alt = isLive ? '生成中プレビュー（クリックで拡大）' : '生成プレビュー（クリックで拡大）';
        img.title = 'クリックで拡大表示';
        img.src = src;
        img.loading = 'eager';
        preview.appendChild(img);
    }

    function isGenerateForeverActive() {
        return _pcGenerateForeverActive;
    }

    function stopPcProgressWatch(forceHide) {
        if (_pcProgressTimer) {
            clearTimeout(_pcProgressTimer);
            _pcProgressTimer = null;
        }
        _pcLivePreviewId = -1;
        _pcProgressWasActive = false;
        _pcForeverProgressSession = false;
        if (forceHide !== false) {
            showProgressUi(false);
        }
    }

    function startPcProgressWatch(target, options) {
        options = options || {};
        const foreverSession = !!(options.foreverSession || isGenerateForeverActive());
        if (foreverSession) {
            _pcForeverProgressSession = true;
        }
        _pcProgressTarget = target || 'txt2img';

        if (_pcProgressTimer) {
            clearTimeout(_pcProgressTimer);
            _pcProgressTimer = null;
        }

        if (!options.softRestart) {
            _pcLivePreviewId = -1;
            if (!foreverSession) {
                _pcProgressWasActive = false;
            }
        }

        showProgressUi(true);
        updateProgressUi({
            progress: 0,
            textinfo: foreverSession ? '生成準備中...' : '準備中...'
        });

        const taskKey = _pcProgressTarget === 'img2img' ? 'img2img_task_id' : 'txt2img_task_id';
        const preview = getProgressPreviewHost();
        const startedAt = Date.now();
        let lastTaskId = null;

        const tick = () => {
            let taskId = null;
            try {
                if (typeof localGet === 'function') {
                    taskId = localGet(taskKey, null);
                }
            } catch (_) { /* ignore */ }

            const foreverActive = _pcForeverProgressSession && isGenerateForeverActive();

            if (!taskId) {
                if (foreverActive || Date.now() - startedAt < 15000) {
                    if (foreverActive && _pcProgressWasActive) {
                        updateProgressUi({ progress: 0, textinfo: '次の生成を待機中...' });
                    }
                    _pcProgressTimer = setTimeout(tick, foreverActive ? 250 : 300);
                    return;
                }
                stopPcProgressWatch();
                return;
            }

            if (taskId !== lastTaskId) {
                lastTaskId = taskId;
                _pcLivePreviewId = -1;
                if (taskId) {
                    updateProgressUi({ progress: 0, textinfo: '生成開始...' });
                }
            }

            fetchInternalProgress({
                id_task: taskId,
                id_live_preview: _pcLivePreviewId,
                live_preview: true
            }).then(res => {
                if (res.active) _pcProgressWasActive = true;

                const generationEnded = res.completed
                    || (_pcProgressWasActive && !res.active && !res.queued);

                if (generationEnded) {
                    syncGeneratePreview(_pcProgressTarget);

                    if (foreverActive) {
                        _pcLivePreviewId = -1;
                        _pcProgressWasActive = false;
                        lastTaskId = null;
                        showProgressUi(true);
                        updateProgressUi({ progress: 0, textinfo: '次の生成を待機中...' });
                        _pcProgressTimer = setTimeout(tick, 250);
                        return;
                    }

                    stopPcProgressWatch();
                    return;
                }

                updateProgressUi(res);

                if (res.live_preview && preview) {
                    setPreviewImage(preview, res.live_preview, true);
                    if (res.id_live_preview != null) {
                        _pcLivePreviewId = res.id_live_preview;
                    }
                } else if (preview && !preview.querySelector('img')) {
                    preview.innerHTML = '<span class="pc-generate-preview-empty">生成中...（ライブプレビューは設定で有効化）</span>';
                }

                _pcProgressTimer = setTimeout(tick, getProgressRefreshMs());
            }).catch(() => {
                _pcProgressTimer = setTimeout(tick, foreverActive ? 400 : 1000);
            });
        };

        tick();
    }

    function syncGeneratePreview() {
        /* 画像は Output タブのギャラリーに表示（右サイドバーには出さない） */
    }

    function ensureGalleryObserver() {
        if (_galleryObserver) return;
        const container = appRoot().querySelector('#pc_txt2img_output_col_left #txt2img_gallery_container')
            || appRoot().querySelector('#txt2img_gallery_container')
            || appRoot().querySelector('#txt2img_gallery');
        if (!container) return;

        _galleryObserver = new MutationObserver(() => syncGeneratePreview('txt2img'));
        _galleryObserver.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
    }

    /** Switch to the top-level txt2img tab (Gradio 3/4 + extension tabs). */
    function switchToTxt2imgTab() {
        const root = appRoot();
        const tabsRoot = root.querySelector('#tabs');
        if (!tabsRoot) return false;

        const tabButtons = tabsRoot.querySelectorAll(
            '.tab-nav button, .tab-nav > button, div.tab-nav button, :scope > button'
        );

        const findByLabel = () => Array.from(tabButtons).find(btn => {
            const label = (btn.textContent || btn.innerText || '').trim();
            return /^txt2img$/i.test(label);
        });

        let targetBtn = findByLabel();

        if (!targetBtn) {
            targetBtn = tabsRoot.querySelector(
                'button[id*="txt2img" i], button[aria-controls*="txt2img" i]'
            );
        }

        if (!targetBtn) {
            const panel = root.getElementById('tab_txt2img');
            const panelId = panel && panel.id;
            if (panelId) {
                targetBtn = tabsRoot.querySelector(
                    `button[aria-controls="${panelId}"], button[data-tab="${panelId}"]`
                );
            }
        }

        // WebUI global (index-based; safe when txt2img is still the first tab)
        if (!targetBtn && typeof window.switch_to_txt2img === 'function') {
            try {
                window.switch_to_txt2img();
                return true;
            } catch (err) {
                console.warn('[Prompt Composer] switch_to_txt2img failed:', err);
            }
        }

        if (!targetBtn && tabButtons.length) {
            targetBtn = tabButtons[0];
        }

        if (targetBtn) {
            targetBtn.click();
            return true;
        }
        return false;
    }

    function scrollToTxt2imgGallery() {
        const root = appRoot();
        const gallery = root.querySelector('#pc_txt2img_output_col_left #txt2img_gallery')
            || root.querySelector('#txt2img_gallery')
            || root.querySelector('#txt2img_gallery_container');
        const tabPanel = root.getElementById('tab_txt2img');
        const target = gallery || tabPanel;
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    function openTxt2imgGalleryTab(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        const switched = switchToTxt2imgTab();
        if (!switched) {
            console.warn('[Prompt Composer] txt2img tab button not found');
        }
        requestAnimationFrame(() => {
            setTimeout(scrollToTxt2imgGallery, 50);
            setTimeout(scrollToTxt2imgGallery, 250);
        });
    }

    function setupGeneratePreview() {
        const root = appRoot();
        // Delegation survives Gradio DOM refreshes better than a single-node listener.
        if (root.dataset.pcOpenTxt2imgDelegation !== '1') {
            root.dataset.pcOpenTxt2imgDelegation = '1';
            root.addEventListener('click', (ev) => {
                const previewImg = ev.target && ev.target.closest
                    ? ev.target.closest('#pc_generate_preview .pc-generate-preview-img')
                    : null;
                if (previewImg) {
                    openPreviewLightbox(previewImg.currentSrc || previewImg.src, ev);
                    return;
                }
                const galleryImg = ev.target && ev.target.closest
                    ? ev.target.closest('#pc_txt2img_output_col_left #txt2img_gallery img, #txt2img_gallery img')
                    : null;
                if (galleryImg && galleryImg.src) {
                    openPreviewLightbox(galleryImg.currentSrc || galleryImg.src, ev);
                    return;
                }
                const hit = ev.target && ev.target.closest
                    ? ev.target.closest('#pc_open_txt2img_gallery')
                    : null;
                if (hit) openTxt2imgGalleryTab(ev);
            });
        }
        ensureGalleryObserver();
    }

    function readGradioFieldValue(elemId) {
        const host = appRoot().getElementById(elemId);
        if (!host) return '';
        const ta = host.querySelector('textarea');
        if (ta) return (ta.value || '').trim();
        const input = host.querySelector('input');
        if (input) return (input.value || '').trim();
        const selected = host.querySelector('span.single-select, .selected');
        if (selected) return (selected.textContent || '').trim();
        return '';
    }

    function readTxt2imgScriptChoice() {
        const scriptList = appRoot().querySelector('#script_list');
        if (!scriptList) return 'None';
        const input = scriptList.querySelector('input, textarea');
        if (input && (input.value || '').trim()) return input.value.trim();
        const selected = scriptList.querySelector('span.single-select, .selected');
        if (selected && (selected.textContent || '').trim()) return selected.textContent.trim();
        return 'None';
    }

    /** X/Y/Z plot with empty axis values yields 0 images (xyz_grid.py). */
    function getXyzPlotZeroImageMessage() {
        const script = readTxt2imgScriptChoice();
        if (!script || script === 'None' || script.toLowerCase().indexOf('x/y/z') < 0) {
            return null;
        }
        const axes = [
            { axis: 'X', typeId: 'script_txt2img_xyz_plot_x_type', valuesId: 'script_txt2img_xyz_plot_x_values' },
            { axis: 'Y', typeId: 'script_txt2img_xyz_plot_y_type', valuesId: 'script_txt2img_xyz_plot_y_values' },
            { axis: 'Z', typeId: 'script_txt2img_xyz_plot_z_type', valuesId: 'script_txt2img_xyz_plot_z_values' },
        ];
        for (let i = 0; i < axes.length; i++) {
            const { axis, typeId, valuesId } = axes[i];
            const typeLabel = readGradioFieldValue(typeId);
            if (!typeLabel || typeLabel === 'Nothing') continue;
            if (!readGradioFieldValue(valuesId)) {
                return (
                    'X/Y/Z plot が有効ですが、' + axis + ' 軸（' + typeLabel + '）の値が空のため画像が 0 枚になります。\n\n' +
                    '対処:\n' +
                    '・Generation タブの Script を「None」にする\n' +
                    '・または ' + axis + ' values に数値を入力（例: 1-3 や -1）\n' +
                    '・または ' + axis + ' type を「Nothing」にする'
                );
            }
        }
        return null;
    }

    function notifyTxt2imgGenerationStart() {
        try {
            window.dispatchEvent(new CustomEvent('pc-txt2img-generation-start'));
        } catch (_) { /* ignore */ }
    }

    function generateTxt2img() {
        const prompt = getFinalPrompt();
        const negative = getFinalNegative();
        if (!prompt && !negative) {
            alert('プロンプトが空です');
            return;
        }

        const xyzMsg = getXyzPlotZeroImageMessage();
        if (xyzMsg) {
            alert(xyzMsg);
            return;
        }

        applyToTarget('txt2img');

        setTimeout(() => {
            const genBtn = getGenerateButton('txt2img');
            if (!genBtn) {
                alert('txt2img の生成ボタンが見つかりません');
                stopPcProgressWatch();
                return;
            }
            genBtn.click();
            notifyTxt2imgGenerationStart();
            ensureGalleryObserver();
            startPcProgressWatch('txt2img', { foreverSession: isGenerateForeverActive() });
        }, 150);
    }

    function getInterruptEl(target) {
        const root = appRoot();
        return root.querySelector(`#${target}_interrupt button`)
            || root.querySelector(`#${target}_interrupt`);
    }

    function triggerTxt2imgGenerateOnce() {
        const prompt = getFinalPrompt();
        const negative = getFinalNegative();
        if (!prompt && !negative) return false;

        if (getXyzPlotZeroImageMessage()) return false;

        applyToTarget('txt2img');

        const genBtn = getGenerateButton('txt2img');
        if (!genBtn) return false;
        genBtn.click();
        notifyTxt2imgGenerationStart();
        ensureGalleryObserver();
        if (isGenerateForeverActive()) {
            if (!_pcForeverProgressSession || !_pcProgressTimer) {
                startPcProgressWatch('txt2img', { foreverSession: true });
            } else {
                showProgressUi(true);
                updateProgressUi({ progress: 0, textinfo: '生成開始...' });
            }
        } else {
            startPcProgressWatch('txt2img');
        }
        return true;
    }

    function notifyGenerateForeverChanged() {
        try {
            window.dispatchEvent(new CustomEvent('pc-generate-forever-changed'));
        } catch (_) { /* ignore */ }
    }

    function cancelGenerateForeverTxt2img() {
        resetGenerateForeverLoop();
        _pcForeverProgressSession = false;

        if (isTxt2imgGenerationInProgress()) {
            showProgressUi(true);
            if (!_pcProgressTimer) {
                startPcProgressWatch('txt2img');
            } else {
                updateProgressUi({ progress: 0, textinfo: '生成中...' });
            }
        } else {
            stopPcProgressWatch();
        }

        notifyGenerateForeverChanged();
    }

    function generateForeverTxt2img() {
        const genBtn = getGenerateButton('txt2img');
        const interruptEl = getInterruptEl('txt2img');
        if (!genBtn || !interruptEl) return false;

        setGenerateForeverActive(true);
        _pcForeverProgressSession = true;
        showProgressUi(true);
        updateProgressUi({ progress: 0, textinfo: '連続生成を開始...' });

        if (!interruptEl.offsetParent) {
            if (!triggerTxt2imgGenerateOnce()) return false;
        } else {
            startPcProgressWatch('txt2img', { foreverSession: true });
        }

        clearInterval(window.generateOnRepeatInterval);
        window.generateOnRepeatInterval = setInterval(function () {
            if (!interruptEl.offsetParent) {
                triggerTxt2imgGenerateOnce();
            }
        }, 500);
        notifyTxt2imgGenerationStart();
        notifyGenerateForeverChanged();
        return true;
    }

    /** Bind each button at most once per DOM node (Gradio re-creates nodes without our flag). */
    function setupButtons() {
        const bindOnce = (elemId, handler) => {
            const btn = getButtonEl(elemId);
            if (!btn || btn.dataset.pcPromptSyncBound === '1') return;
            btn.dataset.pcPromptSyncBound = '1';
            if (!btn.dataset.pcPromptSyncOrigLabel) {
                btn.dataset.pcPromptSyncOrigLabel = (btn.textContent || '').trim();
            }
            btn.addEventListener('click', handler);
        };

        // NOTE: Do not also handle these via document delegation — that fired applyToTarget twice
        // per click; the second run saved "✅ 適用しました" as the "original" label and stuck the UI.

        bindOnce('pc_apply_txt2img', (e) => {
            e.preventDefault();
            applyToTarget('txt2img');
        });

        bindOnce('pc_apply_img2img', (e) => {
            e.preventDefault();
            applyToTarget('img2img');
        });

        bindOnce('pc_copy_clipboard', (e) => {
            e.preventDefault();
            copyToClipboard();
        });

        bindOnce('pc_generate_txt2img', (e) => {
            e.preventDefault();
            generateTxt2img();
        });
    }

    let _setupButtonsDebounce = null;
    function scheduleSetupButtons() {
        if (_setupButtonsDebounce) clearTimeout(_setupButtonsDebounce);
        _setupButtonsDebounce = setTimeout(() => {
            _setupButtonsDebounce = null;
            setupButtons();
            setupGeneratePreview();
        }, 400);
    }

    function getTextareaValue(elemId) {
        const el = appRoot().getElementById(elemId);
        if (!el) return '';
        const ta = el.querySelector('textarea');
        return ta ? ta.value : '';
    }

    function getFinalPrompt() {
        return getTextareaValue('txt2img_prompt') || getTextareaValue('pc_final_prompt');
    }

    function getFinalNegative() {
        return getTextareaValue('txt2img_neg_prompt') || getTextareaValue('pc_final_negative');
    }

    function applyToTarget(target) {
        const prompt = getFinalPrompt();
        const negative = getFinalNegative();

        if (!prompt && !negative) {
            return;
        }

        // Find WebUI prompt textareas
        let promptSelector, negSelector;
        if (target === 'txt2img') {
            promptSelector = '#txt2img_prompt textarea';
            negSelector = '#txt2img_neg_prompt textarea';
        } else {
            promptSelector = '#img2img_prompt textarea';
            negSelector = '#img2img_neg_prompt textarea';
        }

        const root = appRoot();
        const promptArea = root.querySelector(promptSelector);
        const negArea = root.querySelector(negSelector);

        const dispatchPromptEvents = (ta) => {
            try {
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (err) {
                console.warn('[Prompt Composer] prompt field event (WebUI may still have updated):', err);
            }
        };

        if (promptArea && prompt) {
            promptArea.value = prompt;
            dispatchPromptEvents(promptArea);
        }

        if (negArea && negative) {
            negArea.value = negative;
            dispatchPromptEvents(negArea);
        }

        // Visual feedback (restore from data attribute — safe if label was already overwritten)
        const btn = getButtonEl(target === 'txt2img' ? 'pc_apply_txt2img' : 'pc_apply_img2img');
        if (btn) {
            const restore =
                (btn.dataset.pcPromptSyncOrigLabel && btn.dataset.pcPromptSyncOrigLabel.trim()) ||
                (btn.textContent || '').trim();
            btn.textContent = '✅ 適用しました';
            setTimeout(() => {
                btn.textContent = restore;
            }, 1500);
        }

        // Switch to the target tab
        const tabBtn = appRoot().querySelector(`#tabs button[data-index="${target === 'txt2img' ? '0' : '1'}"]`)
            || appRoot().querySelector(`button#${target}_tab`)
            || appRoot().querySelector(`#tab_${target} button`);
        // Don't auto-switch - let user decide
    }

    async function copyToClipboard() {
        const prompt = getFinalPrompt();
        const negative = getFinalNegative();

        let text = prompt;
        if (negative) {
            text += '\n\nNegative prompt: ' + negative;
        }

        try {
            await navigator.clipboard.writeText(text);
            const btn = getButtonEl('pc_copy_clipboard');
            if (btn) {
                const restore =
                    (btn.dataset.pcPromptSyncOrigLabel && btn.dataset.pcPromptSyncOrigLabel.trim()) ||
                    (btn.textContent || '').trim();
                btn.textContent = '✅ コピーしました';
                setTimeout(() => {
                    btn.textContent = restore;
                }, 1500);
            }
        } catch (err) {
            // Fallback for non-HTTPS
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
    }

    window.PromptSync = {
        init,
        applyToTarget,
        copyToClipboard,
        generateTxt2img,
        generateForeverTxt2img,
        cancelGenerateForeverTxt2img,
        isGenerateForeverActive,
        setGenerateForeverActive,
        resetGenerateForeverState,
        syncGeneratePreview,
        startPcProgressWatch,
        stopPcProgressWatch,
        openTxt2imgGalleryTab,
        switchToTxt2imgTab,
        openPreviewLightbox,
        closePcPreviewLightbox
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 2000));
    } else {
        setTimeout(init, 2000);
    }

    // Tab switches and Gradio updates mutate the whole tree; debounce and only
    // re-bind buttons (idempotent) — never stack duplicate click listeners.
    const observer = new MutationObserver(() => {
        scheduleSetupButtons();
    });
    function startPromptSyncObserver() {
        let rootDoc;
        try {
            rootDoc = appRoot();
        } catch (_) {
            rootDoc = document;
        }
        const target = rootDoc.body || rootDoc.documentElement;
        if (!(target instanceof Node)) {
            requestAnimationFrame(startPromptSyncObserver);
            return;
        }
        try {
            observer.observe(target, { childList: true, subtree: true });
        } catch (_) {
            requestAnimationFrame(startPromptSyncObserver);
        }
    }
    startPromptSyncObserver();

})();
