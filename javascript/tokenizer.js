/**
 * Lightweight tokenizer preview for Prompt Composer.
 * This is an approximate tokenizer (token_text only), designed to be fast.
 */
(function() {
    'use strict';

    const CACHE = new Map(); // text -> { token_count, max_length, tokens }
    let inflight = null;

    function init() {
        const promptBox = document.getElementById('pc_final_prompt');
        const view = document.getElementById('pc_tokenizer_view');
        const button = document.getElementById('pc_tokenizer_button');
        if (!promptBox || !view) {
            setTimeout(init, 800);
            return;
        }

        const textarea = promptBox.querySelector('textarea');
        if (!textarea) {
            setTimeout(init, 800);
            return;
        }

        let debounceTimer = null;
        const handler = () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                // Approx のみ更新（正確トークン数は保持済みデータがあれば表示）
                updateTokenizer(textarea.value || '');
            }, 250);
        };

        textarea.addEventListener('input', handler);
        // 手動計算ボタン
        if (button && !button.dataset._pcBound) {
            button.dataset._pcBound = '1';
            button.addEventListener('click', () => {
                requestExactTokenize(textarea.value || '');
            });
        }

        // 初期表示（Approx のみ）
        updateTokenizer(textarea.value || '');

        console.log('[Prompt Composer] Lightweight tokenizer initialized (manual exact count)');
    }

    function tokenizeApprox(text) {
        const maxLen = 512;
        let src = (text || '').trim();
        if (!src) return [];
        if (src.length > maxLen) {
            src = src.slice(0, maxLen);
        }
        const rough = src.split(/\s+/);
        const tokens = [];
        rough.forEach(w => {
            const parts = w.match(/[\p{L}\p{N}_]+|[^\p{L}\p{N}_\s]/gu);
            if (parts) tokens.push(...parts);
        });
        return tokens;
    }

    function updateTokenizer(text) {
        const view = document.getElementById('pc_tokenizer_view');
        if (!view) return;

        const tokens = tokenizeApprox(text);
        if (!tokens.length) {
            const exact = CACHE.get(normalizeKey(text));
            const exactPart = exact ? ` / exact: ${exact.token_count}` : '';
            view.innerHTML = `<span class="pc-tokenizer-empty">トークンなし${exactPart}</span>`;
            return;
        }

        const total = tokens.length;
        const chunks = Math.ceil(total / 75);
        const exact = CACHE.get(normalizeKey(text));
        const exactText = exact ? ` / exact: ${exact.token_count} (max ${exact.max_length})` : ' / exact: …';

        let html = `<div class="pc-tokenizer-summary">` +
            `Approx: ${total} / chunks: ${chunks} (75/chunk)${exactText}` +
            `</div>`;

        // warning based on exact token count if available
        if (exact && exact.token_count > 75) {
            const over = exact.token_count - 75;
            const exactChunks = Math.ceil(exact.token_count / 75);
            html += `<div class="pc-tokenizer-warning"><strong>⚠️ 75トークン超過</strong>: exact ${exact.token_count} tokens（+${over}） / chunks: ${exactChunks}</div>`;
        } else if (exact && exact.token_count === 75) {
            html += `<div class="pc-tokenizer-warning"><strong>⚠️ 上限</strong>: exact 75 tokens に到達しています</div>`;
        }

        html += '<div class="pc-tokenizer-chips">';

        const displayTokensRaw = (exact && Array.isArray(exact.tokens) && exact.tokens.length) ? exact.tokens : tokens;
        const displayTokens = displayTokensRaw.map(t => normalizeDisplayToken(t));
        displayTokens.forEach((tok, idx) => {
            const chunkIdx = Math.floor(idx / 75);
            if (idx % 75 === 0) {
                html += `<div class="pc-tokenizer-chunk-label">Chunk ${chunkIdx + 1}</div>`;
            }
            const isLimit = idx === 74; // 75th (1-indexed)
            if (isLimit) {
                html += `<div class="pc-tokenizer-limit-marker">75トークン（BREAK目安）</div>`;
            }
            const cls = `pc-token-chip pc-token-chip-${chunkIdx % 4}` + (isLimit ? ' pc-token-chip-limit' : '');
            const title = isLimit ? `#${idx + 1} (75 token / BREAK目安)` : `#${idx + 1}`;
            html += `<span class="${cls}" title="${escapeHtml(title)}">${escapeHtml(tok)}</span>`;
        });

        html += '</div>';
        view.innerHTML = html;
    }

    function normalizeKey(text) {
        const maxLen = 2048;
        return (text || '').slice(0, maxLen);
    }

    async function requestExactTokenize(text) {
        const key = normalizeKey(text);
        if (!key.trim()) return;
        if (CACHE.has(key)) return;

        // avoid spamming: keep only one inflight request; last-write wins
        inflight = key;
        try {
            const params = new URLSearchParams({ text: key });
            const resp = await fetch('/prompt-composer/api/tokenize?' + params.toString());
            if (!resp.ok) return;
            const data = await resp.json();
            if (inflight !== key) return;
            if (typeof data.token_count !== 'number') return;

            CACHE.set(key, {
                token_count: data.token_count,
                max_length: data.max_length || 0,
                tokens: Array.isArray(data.tokens) ? data.tokens : []
            });

            // refresh view if still showing same text
            const promptBox = document.getElementById('pc_final_prompt');
            const ta = promptBox ? promptBox.querySelector('textarea') : null;
            if (ta && normalizeKey(ta.value) === key) {
                updateTokenizer(ta.value || '');
            }
        } catch (e) {
            // ignore
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function normalizeDisplayToken(tok) {
        let s = String(tok ?? '');
        // OpenCLIP BPE often returns tokens with word-end markers like </w>
        s = s.replaceAll('</w>', '');
        s = s.replaceAll('<w>', '');
        return s;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(() => { init(); }, 1500));
    } else {
        setTimeout(() => { init(); }, 1500);
    }

})();

