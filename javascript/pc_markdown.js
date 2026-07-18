/**
 * Lightweight Markdown renderer for character memo preview (no external deps).
 */
(function () {
    'use strict';

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function renderInline(text) {
        let out = escapeHtml(text);
        out = out.replace(/`([^`\n]+)`/g, '<code class="pc-md-code">$1</code>');
        out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
        out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
        return out;
    }

    function renderMarkdown(source) {
        const text = String(source || '');
        if (!text.trim()) {
            return '<p class="pc-md-empty">（メモなし）</p>';
        }

        const lines = text.replace(/\r\n/g, '\n').split('\n');
        const parts = [];
        let inUl = false;
        let inOl = false;

        function closeLists() {
            if (inUl) {
                parts.push('</ul>');
                inUl = false;
            }
            if (inOl) {
                parts.push('</ol>');
                inOl = false;
            }
        }

        lines.forEach((rawLine) => {
            const line = rawLine.trimEnd();
            const trimmed = line.trim();

            if (!trimmed) {
                closeLists();
                parts.push('<div class="pc-md-spacer"></div>');
                return;
            }

            const h3 = trimmed.match(/^###\s+(.+)$/);
            if (h3) {
                closeLists();
                parts.push(`<h4 class="pc-md-h4">${renderInline(h3[1])}</h4>`);
                return;
            }
            const h2 = trimmed.match(/^##\s+(.+)$/);
            if (h2) {
                closeLists();
                parts.push(`<h3 class="pc-md-h3">${renderInline(h2[1])}</h3>`);
                return;
            }
            const h1 = trimmed.match(/^#\s+(.+)$/);
            if (h1) {
                closeLists();
                parts.push(`<h2 class="pc-md-h2">${renderInline(h1[1])}</h2>`);
                return;
            }

            const ul = trimmed.match(/^[-*+]\s+(.+)$/);
            if (ul) {
                if (!inUl) {
                    closeLists();
                    parts.push('<ul class="pc-md-ul">');
                    inUl = true;
                }
                parts.push(`<li>${renderInline(ul[1])}</li>`);
                return;
            }

            const ol = trimmed.match(/^\d+\.\s+(.+)$/);
            if (ol) {
                if (!inOl) {
                    closeLists();
                    parts.push('<ol class="pc-md-ol">');
                    inOl = true;
                }
                parts.push(`<li>${renderInline(ol[1])}</li>`);
                return;
            }

            const quote = trimmed.match(/^>\s?(.+)$/);
            if (quote) {
                closeLists();
                parts.push(`<blockquote class="pc-md-quote">${renderInline(quote[1])}</blockquote>`);
                return;
            }

            closeLists();
            parts.push(`<p class="pc-md-p">${renderInline(trimmed)}</p>`);
        });

        closeLists();
        return parts.join('');
    }

    window.PcMarkdown = {
        render: renderMarkdown,
        escapeHtml
    };
})();
