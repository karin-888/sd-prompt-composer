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

    function init() {
        setupButtons();
        if (!_syncLogged) {
            _syncLogged = true;
            console.log('[Prompt Composer] Prompt Sync initialized');
        }
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
    }

    let _setupButtonsDebounce = null;
    function scheduleSetupButtons() {
        if (_setupButtonsDebounce) clearTimeout(_setupButtonsDebounce);
        _setupButtonsDebounce = setTimeout(() => {
            _setupButtonsDebounce = null;
            setupButtons();
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

    window.PromptSync = { init, applyToTarget, copyToClipboard };

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
