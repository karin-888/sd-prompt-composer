/**
 * Mirror txt2img "Script" dropdown and its active settings under Prompt Composer.
 * Dropdown: native select synced with txt2img. Panel: live DOM reparent (Gradio-native).
 */
(function () {
    'use strict';

    var retryCount = 0;
    var debounceTimer = null;
    var panelDebounceTimer = null;
    var pollTimer = null;
    var reparentState = { panel: null, parent: null, next: null };

    function appRoot() {
        try {
            if (typeof window.gradioApp === 'function') return window.gradioApp();
        } catch (_) { /* ignore */ }
        return document.getElementById('gradio-app') || document;
    }

    function findMount() {
        return appRoot().getElementById('pc_script_mount');
    }

    function findScriptContainer() {
        return appRoot().querySelector('#txt2img_script_container');
    }

    function findTxt2imgScriptBlock() {
        var container = findScriptContainer();
        if (!container) return null;
        return container.querySelector('#script_list');
    }

    function findScriptContext(container) {
        if (!container) return null;
        var scriptList = container.querySelector('#script_list');
        if (!scriptList) return null;

        var root = container;
        if (container.children.length === 1 && container.firstElementChild.contains(scriptList)) {
            root = container.firstElementChild;
        }

        var host = null;
        Array.from(root.children).forEach(function (child) {
            if (child.contains(scriptList) || child.id === 'script_list') {
                host = child;
            }
        });

        return { container: container, root: root, host: host, scriptList: scriptList };
    }

    function isNegpipBlock(el) {
        if (!el) return false;
        var accordions = el.matches && el.matches('.input-accordion-m')
            ? [el]
            : Array.from(el.querySelectorAll('.input-accordion-m'));
        for (var i = 0; i < accordions.length; i++) {
            var acc = accordions[i];
            var labelWrap = acc.querySelector('.label-wrap');
            var text = (labelWrap ? labelWrap.textContent : acc.textContent) || '';
            if (/NegPiP/i.test(text)) return true;
        }
        return false;
    }

    function findSelectableScriptPanels(container) {
        var ctx = findScriptContext(container);
        if (!ctx || !ctx.host) return [];

        var panels = [];
        var afterHost = false;
        Array.from(ctx.root.children).forEach(function (child) {
            if (child === ctx.host || child.contains(ctx.scriptList)) {
                afterHost = true;
                return;
            }
            if (afterHost && !isNegpipBlock(child)) {
                panels.push(child);
            }
        });
        return panels;
    }

    function titleToElemPrefix(title) {
        var slug = (title || '').toLowerCase().replace(/\s/g, '_').replace(/[^a-z0-9_]/g, '');
        return 'script_txt2img_' + slug + '_';
    }

    function findScriptIndex(titles, choice) {
        if (!titles || !choice) return -1;
        var idx = titles.indexOf(choice);
        if (idx >= 0) return idx;
        var lower = choice.toLowerCase();
        for (var i = 0; i < titles.length; i++) {
            if ((titles[i] || '').toLowerCase() === lower) return i;
        }
        return -1;
    }

    function panelMatchesChoice(panel, choice) {
        if (!panel || !choice) return false;

        var prefix = titleToElemPrefix(choice);
        if (panel.querySelector('[id^="' + prefix + '"]')) return true;

        var text = (panel.innerText || '').replace(/\s+/g, ' ').toLowerCase();
        var c = choice.toLowerCase();

        if (c.indexOf('x/y/z') >= 0) {
            return text.indexOf('x type') >= 0 && text.indexOf('y type') >= 0;
        }
        if (c.indexOf('prompt travel') >= 0) {
            return text.indexOf('travel mode') >= 0;
        }
        if (c.indexOf('prompt matrix') >= 0) {
            return text.indexOf('variable parts') >= 0 || text.indexOf('different seed') >= 0;
        }
        if (c.indexOf('prompts from file') >= 0 || c.indexOf('textbox') >= 0) {
            return text.indexOf('iterate seed every line') >= 0;
        }
        if (c.indexOf('test my prompt') >= 0) {
            return text.indexOf('test negative or positive') >= 0;
        }
        return false;
    }

    function findSelectablePanelForChoice(container, choice, scriptTitles) {
        if (!container || !choice || choice === 'None') return null;

        var selectable = findSelectableScriptPanels(container);
        for (var i = 0; i < selectable.length; i++) {
            if (panelMatchesChoice(selectable[i], choice)) {
                return selectable[i];
            }
        }

        var idx = findScriptIndex(scriptTitles, choice);
        if (idx > 0 && selectable[idx - 1]) return selectable[idx - 1];
        return null;
    }

    function unhidePanel(el) {
        if (!el) return;
        el.hidden = false;
        el.classList.remove('hidden', 'hide');
        el.style.removeProperty('display');
        el.style.removeProperty('visibility');
        el.style.removeProperty('opacity');
    }

    function restoreReparentedPanel() {
        if (!reparentState.panel || !reparentState.parent) return;
        var panel = reparentState.panel;
        var parent = reparentState.parent;
        var next = reparentState.next;
        panel.classList.remove('pc-script-panel-live');
        try {
            if (next && next.parentNode === parent) {
                parent.insertBefore(panel, next);
            } else {
                parent.appendChild(panel);
            }
        } catch (_) { /* ignore */ }
        reparentState.panel = null;
        reparentState.parent = null;
        reparentState.next = null;
    }

    function reparentPanelToMount(panel, panelMount) {
        if (!panel || !panelMount) return false;

        if (reparentState.panel === panel && panel.parentElement === panelMount) {
            unhidePanel(panel);
            return true;
        }

        if (reparentState.panel && reparentState.panel !== panel) {
            restoreReparentedPanel();
        }

        reparentState.parent = panel.parentElement;
        reparentState.next = panel.nextElementSibling;
        reparentState.panel = panel;
        panel.classList.add('pc-script-panel-live');
        unhidePanel(panel);
        panelMount.appendChild(panel);
        return true;
    }

    function getScriptInput(dropdownRoot) {
        if (!dropdownRoot) return null;
        return dropdownRoot.querySelector('input[type="text"]')
            || dropdownRoot.querySelector('textarea')
            || dropdownRoot.querySelector('select')
            || dropdownRoot.querySelector('input:not([type="checkbox"]):not([type="hidden"])');
    }

    function triggerMouseEvent(element, eventName) {
        if (!element) return;
        element.dispatchEvent(new MouseEvent(eventName || 'click', {
            view: window,
            bubbles: true,
            cancelable: true,
        }));
    }

    function readScriptChoice(dropdownRoot) {
        if (!dropdownRoot) return 'None';
        var input = getScriptInput(dropdownRoot);
        if (input && (input.value || '').trim()) {
            return (input.value || '').trim();
        }
        var selected = dropdownRoot.querySelector('span.single-select, .selected');
        if (selected && (selected.textContent || '').trim()) {
            return selected.textContent.trim();
        }
        return 'None';
    }

    function findDropdownListItem(dropdownRoot, choice) {
        if (!dropdownRoot || !choice) return null;
        var items = Array.from(dropdownRoot.querySelectorAll('ul li'));
        var target = (choice || '').trim();
        for (var i = 0; i < items.length; i++) {
            var text = (items[i].textContent || '').replace(/\s+/g, ' ').trim();
            if (text === target) return items[i];
        }
        var lower = target.toLowerCase();
        for (var j = 0; j < items.length; j++) {
            var t2 = (items[j].textContent || '').replace(/\s+/g, ' ').trim();
            if (t2.toLowerCase() === lower) return items[j];
        }
        return null;
    }

    /**
     * Gradio 3 Dropdown must be changed by selecting a list item (setting input.value alone
     * does not run script visibility handlers).
     */
    function selectGradioDropdownOption(dropdownRoot, choice) {
        var next = (choice || 'None').trim() || 'None';
        if (!dropdownRoot) return Promise.resolve(false);

        var current = readScriptChoice(dropdownRoot);
        if (current === next) return Promise.resolve(false);

        var input = getScriptInput(dropdownRoot);
        if (!input) return Promise.resolve(false);

        return new Promise(function (resolve) {
            triggerMouseEvent(input, 'mousedown');
            input.focus();

            setTimeout(function () {
                var item = findDropdownListItem(dropdownRoot, next);
                if (item) {
                    triggerMouseEvent(item, 'mousedown');
                    triggerMouseEvent(item, 'click');
                } else {
                    input.value = next;
                    if (typeof updateInput === 'function') {
                        try { updateInput(input); } catch (_) { /* ignore */ }
                    }
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
                triggerMouseEvent(input, 'blur');
                setTimeout(function () { resolve(true); }, 120);
            }, 120);
        });
    }

    function writeScriptChoice(dropdownRoot, choice) {
        return selectGradioDropdownOption(dropdownRoot, choice);
    }

    function populateSelect(select, scripts) {
        if (!select || !scripts || !scripts.length) return;
        var current = select.value;
        select.innerHTML = '';
        scripts.forEach(function (title) {
            var opt = document.createElement('option');
            opt.value = title;
            opt.textContent = title;
            select.appendChild(opt);
        });
        if (scripts.indexOf(current) >= 0) {
            select.value = current;
        } else {
            select.value = scripts[0] || 'None';
        }
    }

    function fetchScriptTitles() {
        return fetch('/prompt-composer/api/txt2img-scripts')
            .then(function (resp) { return resp.ok ? resp.json() : { scripts: ['None'] }; })
            .then(function (data) {
                return (data && data.scripts && data.scripts.length) ? data.scripts : ['None'];
            })
            .catch(function () { return ['None']; });
    }

    function ensureMirrorUi(mount, scripts) {
        var wrap = mount.querySelector('.pc-script-mirror');
        if (!wrap) {
            mount.innerHTML =
                '<div class="pc-script-mirror block">' +
                '<label class="pc-script-label">Script</label>' +
                '<select class="pc-script-select"></select>' +
                '<div class="pc-script-panel-mount"></div>' +
                '</div>';
            wrap = mount.querySelector('.pc-script-mirror');
        }
        populateSelect(wrap.querySelector('.pc-script-select'), scripts);
        return wrap;
    }

    function getResolvedChoice(wrap, sourceDropdown) {
        var pcSelect = wrap.querySelector('.pc-script-select');
        if (wrap._pcScriptLead && pcSelect && pcSelect.value) {
            return pcSelect.value;
        }
        return readScriptChoice(sourceDropdown);
    }

    function applyScriptChoice(wrap, sourceDropdown, choice, scriptTitles, attempt) {
        if (!wrap || !sourceDropdown) return;

        var panelMount = wrap.querySelector('.pc-script-panel-mount');
        if (!panelMount) return;

        var container = findScriptContainer();
        if (!container) return;

        wrap._pcActiveChoice = choice;
        attempt = attempt || 0;

        if (!choice || choice === 'None') {
            restoreReparentedPanel();
            panelMount.dataset.panelKey = '';
            panelMount.classList.add('is-empty');
            return;
        }

        var panel = findSelectablePanelForChoice(container, choice, scriptTitles);
        if (!panel) {
            if (attempt < 6) {
                setTimeout(function () {
                    applyScriptChoice(wrap, sourceDropdown, choice, scriptTitles, attempt + 1);
                }, 250);
                return;
            }
            restoreReparentedPanel();
            panelMount.dataset.panelKey = '';
            panelMount.classList.add('is-empty');
            return;
        }

        var key = choice + '::' + (panel.id || panel.className || 'panel');
        if (panelMount.dataset.panelKey === key && reparentState.panel === panel) {
            unhidePanel(panel);
            panelMount.classList.remove('is-empty');
            return;
        }

        panelMount.dataset.panelKey = key;
        panelMount.classList.remove('is-empty');
        reparentPanelToMount(panel, panelMount);
    }

    function scheduleApplyChoice(wrap, sourceDropdown, choice, scriptTitles, delay) {
        if (!wrap) return;
        if (panelDebounceTimer) clearTimeout(panelDebounceTimer);
        panelDebounceTimer = setTimeout(function () {
            panelDebounceTimer = null;
            applyScriptChoice(wrap, sourceDropdown, choice, scriptTitles, 0);
        }, delay == null ? 350 : delay);
    }

    function ensureSelectOption(select, value) {
        if (!select || !value) return;
        for (var i = 0; i < select.options.length; i++) {
            if (select.options[i].value === value) return;
        }
        var opt = document.createElement('option');
        opt.value = value;
        opt.textContent = value;
        select.appendChild(opt);
    }

    function bindMirrorSync(mount, source, wrap, scriptTitles) {
        var select = wrap.querySelector('.pc-script-select');
        if (!mount || !source || !select || select.dataset.bound === '1') return;
        select.dataset.bound = '1';
        wrap._pcScriptTitles = scriptTitles;
        wrap._pcScriptLead = false;
        wrap._pcActiveChoice = null;

        function pushPcChoiceToSource() {
            var pcChoice = select.value;
            if (!pcChoice) return;
            writeScriptChoice(source, pcChoice).then(function () {
                scheduleApplyChoice(wrap, source, pcChoice, scriptTitles, 450);
            });
        }

        select.addEventListener('change', function () {
            wrap._pcScriptLead = true;
            pushPcChoiceToSource();
        });

        var sourceInput = getScriptInput(source);
        if (sourceInput) {
            sourceInput.addEventListener('change', function () {
                if (wrap._pcScriptLead) return;
                var srcChoice = readScriptChoice(source);
                ensureSelectOption(select, srcChoice);
                select.value = srcChoice;
                scheduleApplyChoice(wrap, source, srcChoice, scriptTitles, 350);
            });
            sourceInput.addEventListener('input', function () {
                if (wrap._pcScriptLead) return;
                var srcChoice = readScriptChoice(source);
                if (srcChoice === select.value) return;
                ensureSelectOption(select, srcChoice);
                select.value = srcChoice;
                scheduleApplyChoice(wrap, source, srcChoice, scriptTitles, 350);
            });
        }

        // Initial sync: follow txt2img once on mount.
        var initialChoice = readScriptChoice(source);
        ensureSelectOption(select, initialChoice);
        select.value = initialChoice;
        scheduleApplyChoice(wrap, source, initialChoice, scriptTitles, 400);

        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(function () {
            var srcChoice = readScriptChoice(source);
            var pcChoice = select.value;

            if (wrap._pcScriptLead) {
                if (srcChoice !== pcChoice) {
                    writeScriptChoice(source, pcChoice).then(function () {
                        scheduleApplyChoice(wrap, source, pcChoice, scriptTitles, 450);
                    });
                } else {
                    wrap._pcScriptLead = false;
                }
                return;
            }

            if (srcChoice !== pcChoice) {
                ensureSelectOption(select, srcChoice);
                select.value = srcChoice;
                if (srcChoice !== wrap._pcActiveChoice) {
                    scheduleApplyChoice(wrap, source, srcChoice, scriptTitles, 350);
                }
            }
        }, 3000);
    }

    function mountScriptMirror() {
        var mount = findMount();
        if (!mount) return Promise.resolve(false);

        var source = findTxt2imgScriptBlock();
        if (!source) return Promise.resolve(false);

        if (mount.dataset.mounted === '1' && mount.querySelector('.pc-script-select')) {
            var existingSelect = mount.querySelector('.pc-script-select');
            if (existingSelect.dataset.bound === '1' && getScriptInput(source)) {
                return Promise.resolve(true);
            }
            restoreReparentedPanel();
            mount.dataset.mounted = '';
            mount.innerHTML = '';
        }

        return fetchScriptTitles().then(function (scripts) {
            var wrap = ensureMirrorUi(mount, scripts);
            bindMirrorSync(mount, source, wrap, scripts);
            mount.dataset.mounted = '1';
            console.log('[Prompt Composer] txt2img Script mirrored under NegPiP (panel reparented live)');
            return true;
        }).catch(function () { return false; });
    }

    function scheduleMount() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            debounceTimer = null;
            mountScriptMirror().then(function (ok) {
                if (ok) return;
                if (retryCount < 40) {
                    retryCount++;
                    setTimeout(scheduleMount, 500);
                }
            });
        }, 80);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scheduleMount);
    } else {
        scheduleMount();
    }

        try {
        new MutationObserver(function () {
            var mount = findMount();
            if (!mount) {
                if (reparentState.panel) {
                    restoreReparentedPanel();
                }
                return;
            }
            if (!findTxt2imgScriptBlock()) {
                if (mount.dataset.mounted === '1') {
                    restoreReparentedPanel();
                    mount.dataset.mounted = '';
                    mount.innerHTML = '';
                }
                return;
            }
            if (mount.dataset.mounted !== '1') {
                scheduleMount();
            }
        }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_) { /* ignore */ }
})();
