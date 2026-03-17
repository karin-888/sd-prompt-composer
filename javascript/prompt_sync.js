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

    function init() {
        setupButtons();
        setupDelegatedHandlers();
        console.log('[Prompt Composer] Prompt Sync initialized');
    }

    function setupButtons() {
        // Apply to txt2img
        const txt2imgBtn = getButtonEl('pc_apply_txt2img');
        if (txt2imgBtn) {
            txt2imgBtn.addEventListener('click', (e) => {
                e.preventDefault();
                applyToTarget('txt2img');
            });
        }

        // Apply to img2img
        const img2imgBtn = getButtonEl('pc_apply_img2img');
        if (img2imgBtn) {
            img2imgBtn.addEventListener('click', (e) => {
                e.preventDefault();
                applyToTarget('img2img');
            });
        }

        // Copy to clipboard
        const copyBtn = getButtonEl('pc_copy_clipboard');
        if (copyBtn) {
            copyBtn.addEventListener('click', (e) => {
                e.preventDefault();
                copyToClipboard();
            });
        }
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

        if (promptArea && prompt) {
            promptArea.value = prompt;
            promptArea.dispatchEvent(new Event('input', { bubbles: true }));
            // Also dispatch change for Gradio
            promptArea.dispatchEvent(new Event('change', { bubbles: true }));
        }

        if (negArea && negative) {
            negArea.value = negative;
            negArea.dispatchEvent(new Event('input', { bubbles: true }));
            negArea.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // Visual feedback
        const btn = getButtonEl(target === 'txt2img' ? 'pc_apply_txt2img' : 'pc_apply_img2img');
        if (btn) {
            const originalText = btn.textContent;
            btn.textContent = '✅ 適用しました';
            setTimeout(() => { btn.textContent = originalText; }, 1500);
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
                const original = btn.textContent;
                btn.textContent = '✅ コピーしました';
                setTimeout(() => { btn.textContent = original; }, 1500);
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

    let _delegatedInstalled = false;
    function setupDelegatedHandlers() {
        if (_delegatedInstalled) return;
        _delegatedInstalled = true;

        const root = appRoot();
        // Use event delegation so handlers survive Gradio re-renders.
        root.addEventListener('click', (e) => {
            const t = e.target;
            if (!t) return;

            const txtBtn = t.closest ? t.closest('#pc_apply_txt2img, #pc_apply_txt2img button') : null;
            if (txtBtn) {
                e.preventDefault();
                applyToTarget('txt2img');
                return;
            }

            const imgBtn = t.closest ? t.closest('#pc_apply_img2img, #pc_apply_img2img button') : null;
            if (imgBtn) {
                e.preventDefault();
                applyToTarget('img2img');
                return;
            }

            const copyBtn = t.closest ? t.closest('#pc_copy_clipboard, #pc_copy_clipboard button') : null;
            if (copyBtn) {
                e.preventDefault();
                copyToClipboard();
            }
        }, true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 2000));
    } else {
        setTimeout(init, 2000);
    }

    const observer = new MutationObserver((mutations, obs) => {
        // Re-init when Prompt Composer elements are re-rendered
        if (appRoot().getElementById('pc_apply_txt2img')) setTimeout(init, 100);
    });
    observer.observe(document.body, { childList: true, subtree: true });

})();
