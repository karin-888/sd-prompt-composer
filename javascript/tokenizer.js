/**
 * Lightweight tokenizer preview for Prompt Composer.
 * This is an approximate tokenizer (token_text only), designed to be fast.
 */
(function() {
    'use strict';

    const CACHE = new Map(); // scopedKey -> { token_count, max_length, tokens }
    let inflight = null; // scopedKey

    function init() {
        const promptBox = document.getElementById('pc_final_prompt');
        const negBox = document.getElementById('pc_final_negative');
        const view = document.getElementById('pc_tokenizer_view');
        const button = document.getElementById('pc_tokenizer_button');
        if (!promptBox || !view) {
            setTimeout(init, 800);
            return;
        }

        const posTa = promptBox.querySelector('textarea');
        const negTa = negBox ? negBox.querySelector('textarea') : null;
        if (!posTa) {
            setTimeout(init, 800);
            return;
        }

        let debounceTimer = null;
        const handler = () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                // Approx のみ更新（正確トークン数は保持済みデータがあれば表示）
                updateTokenizerPair(posTa.value || '', negTa ? (negTa.value || '') : '');
            }, 250);
        };

        posTa.addEventListener('input', handler);
        if (negTa) negTa.addEventListener('input', handler);
        // 手動計算ボタン
        if (button && !button.dataset._pcBound) {
            button.dataset._pcBound = '1';
            button.addEventListener('click', () => {
                requestExactTokenize('pos', posTa.value || '');
                if (negTa) requestExactTokenize('neg', negTa.value || '');
            });
        }

        // 初期表示（Approx のみ）
        updateTokenizerPair(posTa.value || '', negTa ? (negTa.value || '') : '');

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

    function updateTokenizerPair(posText, negText) {
        const view = document.getElementById('pc_tokenizer_view');
        if (!view) return;

        const posHtml = renderOne('Positive', 'pos', posText);
        const negHtml = renderOne('Negative', 'neg', negText);
        view.innerHTML = `<div class="pc-tokenizer-dual">${posHtml}${negHtml}</div>`;
    }

    function isBreakToken(raw) {
        let s = String(normalizeDisplayToken(raw)).toLowerCase().replace(/<\/w>/g, '').replace(/<w>/g, '').trim();
        s = s.replace(/^[,._]+|[,._]+$/g, '');
        return s === 'break';
    }

    /** Split tokenizer output into segments separated by BREAK; each segment keeps token strings for display. */
    function splitByBreak(rawTokens) {
        const segments = [];
        let buf = [];
        const arr = Array.isArray(rawTokens) ? rawTokens : [];
        for (let i = 0; i < arr.length; i++) {
            const raw = arr[i];
            if (isBreakToken(raw)) {
                segments.push(buf);
                buf = [];
            } else {
                buf.push(raw);
            }
        }
        segments.push(buf);
        return segments;
    }

    /** Per-segment 75-boundary chunk count (for summary). */
    function chunkStepsForSegment(len) {
        return len <= 0 ? 0 : Math.ceil(len / 75);
    }

    function renderOne(title, scope, text) {
        const tokens = tokenizeApprox(text);
        const scopedKey = normalizeKey(scope, text);
        const exact = CACHE.get(scopedKey);

        // Empty
        if (!tokens.length) {
            const exactPart = exact ? ` / exact: ${exact.token_count}` : '';
            return `
                <div class="pc-tokenizer-pane">
                    <div class="pc-tokenizer-summary"><strong>${escapeHtml(title)}</strong> — トークンなし${escapeHtml(exactPart)}</div>
                </div>
            `;
        }

        const displayTokensRaw = (exact && Array.isArray(exact.tokens) && exact.tokens.length) ? exact.tokens : tokens;
        const segments = splitByBreak(displayTokensRaw);
        const breakCount = Math.max(0, segments.length - 1);
        const total = displayTokensRaw.filter(t => !isBreakToken(t)).length;
        const chunkTotal = segments.reduce((sum, seg) => sum + chunkStepsForSegment(seg.length), 0);
        const exactText = exact ? ` / exact: ${exact.token_count} (max ${exact.max_length})` : ' / exact: …';

        let html = `<div class="pc-tokenizer-pane">`;
        html += `<div class="pc-tokenizer-summary"><strong>${escapeHtml(title)}</strong> — ` +
            `Approx: ${total} / BREAK区切り: ${segments.length}セグメント${breakCount ? ` (${breakCount} BREAK)` : ''} / 75換算chunks: ${chunkTotal}${exactText}` +
            `</div>`;

        // Warnings: whole-prompt (legacy) + per-segment when exact available
        if (exact && exact.token_count > 75 && breakCount === 0) {
            const over = exact.token_count - 75;
            const exactChunks = Math.ceil(exact.token_count / 75);
            html += `<div class="pc-tokenizer-warning"><strong>⚠️ 75トークン超過</strong>: exact ${exact.token_count} tokens（+${over}） / chunks: ${exactChunks}</div>`;
        } else if (exact && exact.token_count === 75 && breakCount === 0) {
            html += `<div class="pc-tokenizer-warning"><strong>⚠️ 上限</strong>: exact 75 tokens に到達しています</div>`;
        }
        if (exact && Array.isArray(exact.tokens) && exact.tokens.length) {
            const lens = splitByBreak(exact.tokens).map(s => s.length);
            lens.forEach((L, si) => {
                if (L > 75) {
                    html += `<div class="pc-tokenizer-warning"><strong>⚠️ セグメント${si + 1}が75超</strong>: exact ${L} tokens（BREAKで区切るか短くしてください）</div>`;
                }
            });
        }

        html += '<div class="pc-tokenizer-chips">';

        let segmentIdx = 0;
        segments.forEach((seg, si) => {
            if (!seg.length) return;
            segmentIdx++;
            const chunkLbl = segmentIdx === 1
                ? `Chunk ${segmentIdx}`
                : `Chunk ${segmentIdx}（直前の BREAK 以降・トークン再カウント）`;
            html += `<div class="pc-tokenizer-chunk-label">${escapeHtml(chunkLbl)}</div>`;
            seg.forEach((rawTok, idx) => {
                const tok = normalizeDisplayToken(rawTok);
                const posInSeg = idx % 75;
                const isLimit = posInSeg === 74;
                if (isLimit) {
                    html += `<div class="pc-tokenizer-limit-marker">75トークン（BREAK目安） ― セグメント内 ${idx + 1}番目</div>`;
                }
                const cls = `pc-token-chip pc-token-chip-${si % 4}` + (isLimit ? ' pc-token-chip-limit' : '');
                const chipTitle = isLimit
                    ? `セグメント${segmentIdx} 内 #${idx + 1}（75の境界）`
                    : `セグメント${segmentIdx} 内 #${idx + 1}`;
                html += `<span class="${cls}" title="${escapeHtml(chipTitle)}">${escapeHtml(tok)}</span>`;
            });
            if (si < segments.length - 1) {
                html += `<div class="pc-tokenizer-break-bar" title="BREAK（次のChunkはここから）">BREAK</div>`;
            }
        });

        html += '</div></div>';
        return html;
    }

    function normalizeKey(scope, text) {
        const maxLen = 2048;
        const body = (text || '').slice(0, maxLen);
        return `${scope}:${body}`;
    }

    async function requestExactTokenize(scope, text) {
        const scopedKey = normalizeKey(scope, text);
        const body = (text || '').trim();
        if (!body) return;
        if (CACHE.has(scopedKey)) return;

        // avoid spamming: keep only one inflight request; last-write wins
        inflight = scopedKey;
        try {
            const params = new URLSearchParams({ text: (text || '').slice(0, 2048) });
            const resp = await fetch('/prompt-composer/api/tokenize?' + params.toString());
            if (!resp.ok) return;
            const data = await resp.json();
            if (inflight !== scopedKey) return;
            if (typeof data.token_count !== 'number') return;

            CACHE.set(scopedKey, {
                token_count: data.token_count,
                max_length: data.max_length || 0,
                tokens: Array.isArray(data.tokens) ? data.tokens : []
            });

            // refresh view if still showing same text
            const promptBox = document.getElementById('pc_final_prompt');
            const negBox = document.getElementById('pc_final_negative');
            const posTa = promptBox ? promptBox.querySelector('textarea') : null;
            const negTa = negBox ? negBox.querySelector('textarea') : null;
            if (posTa) {
                updateTokenizerPair(posTa.value || '', negTa ? (negTa.value || '') : '');
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

