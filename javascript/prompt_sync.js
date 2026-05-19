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

    function init() {
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

    function showProgressUi(show) {
        const bar = appRoot().getElementById('pc_generate_progress');
        if (bar) bar.style.display = show ? 'block' : 'none';
    }

    function updateProgressUi(res) {
        const bar = appRoot().getElementById('pc_generate_progress');
        if (!bar) return;
        const fill = bar.querySelector('.pc-generate-progress-fill');
        const textEl = bar.querySelector('.pc-generate-progress-text');
        const pct = Math.max(0, Math.min(100, Math.round((res.progress || 0) * 100)));
        if (fill) {
            fill.style.width = pct + '%';
            fill.style.opacity = res.progress > 0 ? '1' : '0.35';
        }
        let label = '生成中...';
        if (res.textinfo && String(res.textinfo).indexOf('\n') === -1) {
            label = String(res.textinfo).trim();
        }
        if (res.progress > 0) {
            label += (label ? ' ' : '') + pct + '%';
        }
        if (res.eta) {
            label += ' ETA: ' + formatTime(res.eta);
        }
        if (textEl) textEl.textContent = label.trim();
    }

    function setPreviewImage(preview, src, isLive) {
        if (!preview || !src) return;
        if (preview.dataset.pcPreviewSrc === src && !isLive) return;
        preview.dataset.pcPreviewSrc = src;
        preview.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'pc-generate-preview-img' + (isLive ? ' pc-generate-preview-img-live' : '');
        img.alt = isLive ? '生成中プレビュー' : '生成プレビュー';
        img.src = src;
        img.loading = 'eager';
        img.addEventListener('click', () => {
            const openBtn = appRoot().getElementById('pc_open_txt2img_gallery');
            if (openBtn) openBtn.click();
        });
        preview.appendChild(img);
    }

    function stopPcProgressWatch() {
        if (_pcProgressTimer) {
            clearTimeout(_pcProgressTimer);
            _pcProgressTimer = null;
        }
        _pcLivePreviewId = -1;
        _pcProgressWasActive = false;
        showProgressUi(false);
    }

    function startPcProgressWatch(target) {
        stopPcProgressWatch();
        showProgressUi(true);
        updateProgressUi({ progress: 0, textinfo: '準備中...' });

        const taskKey = target === 'img2img' ? 'img2img_task_id' : 'txt2img_task_id';
        const preview = appRoot().getElementById('pc_generate_preview');
        const startedAt = Date.now();

        const tick = () => {
            let taskId = null;
            try {
                if (typeof localGet === 'function') {
                    taskId = localGet(taskKey, null);
                }
            } catch (_) { /* ignore */ }

            if (!taskId) {
                if (Date.now() - startedAt < 15000) {
                    _pcProgressTimer = setTimeout(tick, 300);
                    return;
                }
                stopPcProgressWatch();
                return;
            }

            fetchInternalProgress({
                id_task: taskId,
                id_live_preview: _pcLivePreviewId,
                live_preview: true
            }).then(res => {
                if (res.active) _pcProgressWasActive = true;

                if (res.completed || (_pcProgressWasActive && !res.active && !res.queued)) {
                    stopPcProgressWatch();
                    syncGeneratePreview(target);
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
                _pcProgressTimer = setTimeout(tick, 1000);
            });
        };

        tick();
    }

    function syncGeneratePreview(target) {
        const preview = appRoot().getElementById('pc_generate_preview');
        if (!preview) return;

        const imgs = getGalleryImages(target || 'txt2img');
        if (!imgs.length) {
            preview.innerHTML = '<span class="pc-generate-preview-empty">まだ画像がありません</span>';
            delete preview.dataset.pcPreviewSrc;
            return;
        }

        const last = imgs[imgs.length - 1];
        const src = last.currentSrc || last.src;
        setPreviewImage(preview, src, false);
    }

    function ensureGalleryObserver() {
        if (_galleryObserver) return;
        const container = appRoot().querySelector('#txt2img_gallery_container')
            || appRoot().querySelector('#txt2img_gallery');
        if (!container) return;

        _galleryObserver = new MutationObserver(() => syncGeneratePreview('txt2img'));
        _galleryObserver.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
        syncGeneratePreview('txt2img');
    }

    function setupGeneratePreview() {
        const root = appRoot();
        const openBtn = root.getElementById('pc_open_txt2img_gallery');
        if (openBtn && openBtn.dataset.pcOpenTabBound !== '1') {
            openBtn.dataset.pcOpenTabBound = '1';
            openBtn.addEventListener('click', (e) => {
                e.preventDefault();
                const tab = root.querySelector('#tab_txt2img, button#txt2img_tab, #tabs > .tab-nav button');
                const txt2imgTab = root.querySelector('#tab_txt2img')
                    || Array.from(root.querySelectorAll('#tabs button, .tab-nav button')).find(b => /txt2img/i.test(b.textContent || ''));
                if (txt2imgTab) txt2imgTab.click();
                const gallery = root.querySelector('#txt2img_gallery');
                if (gallery) gallery.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
        }
        ensureGalleryObserver();
    }

    function generateTxt2img() {
        const prompt = getFinalPrompt();
        const negative = getFinalNegative();
        if (!prompt && !negative) {
            alert('プロンプトが空です');
            return;
        }

        applyToTarget('txt2img');

        const preview = appRoot().getElementById('pc_generate_preview');
        if (preview) {
            preview.innerHTML = '<span class="pc-generate-preview-empty">生成を開始しています...</span>';
            delete preview.dataset.pcPreviewSrc;
        }

        setTimeout(() => {
            const genBtn = getGenerateButton('txt2img');
            if (!genBtn) {
                alert('txt2img の生成ボタンが見つかりません');
                stopPcProgressWatch();
                return;
            }
            genBtn.click();
            ensureGalleryObserver();
            startPcProgressWatch('txt2img');
        }, 150);
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

    function getFinalPrompt() {
        const el = appRoot().getElementById('pc_final_prompt');
        if (!el) return '';
        const ta = el.querySelector('textarea');
        return ta ? ta.value : '';
    }

    function getFinalNegative() {
        const el = appRoot().getElementById('pc_final_negative');
        if (!el) return '';
        const ta = el.querySelector('textarea');
        return ta ? ta.value : '';
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
        syncGeneratePreview,
        startPcProgressWatch,
        stopPcProgressWatch
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
