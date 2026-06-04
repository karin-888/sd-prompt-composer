/**

 * Move txt2img output into Prompt Composer tabs.

 * prompt tab: native txt2img prompt / negative.

 * Output tab: gallery + buttons (left), infotext (right).

 */

(function () {

    'use strict';



    var retryCount = 0;

    var debounceTimer = null;

    var moved = false;



    function appRoot() {

        try {

            if (typeof window.gradioApp === 'function') return window.gradioApp();

        } catch (_) { /* ignore */ }

        return document.getElementById('gradio-app') || document.body;

    }



    function findColMount(root, side) {

        return root.getElementById('pc_txt2img_output_col_' + side)

            || root.querySelector('#pc_output_two_col #pc_txt2img_output_col_' + side);

    }



    function findPromptMount(root) {

        return root.getElementById('pc_prompt_tab_prompt_mount')

            || root.querySelector('#pc_final_tab_1 #pc_prompt_tab_prompt_mount');

    }



    function findResultsPanel(root) {

        var el = root.querySelector('#txt2img_results');

        if (el) return el;



        var gallery = root.querySelector('#txt2img_gallery');

        if (gallery) {

            var node = gallery.parentElement;

            for (var i = 0; i < 8 && node; i++) {

                if (node.id === 'txt2img_results') return node;

                node = node.parentElement;

            }

        }



        return null;

    }



    function unhideElement(el) {

        if (!el) return;

        el.classList.remove('hidden');

        el.classList.remove('pc-output-prompt-hidden');

        el.removeAttribute('hidden');

        el.removeAttribute('aria-hidden');

        if (el.style) {

            if (el.style.display === 'none') el.style.display = '';

            if (el.style.visibility === 'hidden') el.style.visibility = '';

            if (el.style.height === '0px' || el.style.height === '0') el.style.height = '';

            if (el.style.minHeight === '0px' || el.style.minHeight === '0') el.style.minHeight = '';

            if (el.style.margin === '0px' || el.style.margin === '0') el.style.margin = '';

            if (el.style.padding === '0px' || el.style.padding === '0') el.style.padding = '';

            if (el.style.overflow === 'hidden') el.style.overflow = '';

        }

    }



    function isPromptBlock(el) {

        if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;

        var id = el.id || '';

        if (id === 'txt2img_prompt' || id === 'txt2img_neg_prompt' || id === 'txt2img_prompt_container') return true;

        if (id === 'txt2img_prompt_row' || id === 'txt2img_neg_prompt_row') return true;

        if (el.querySelector && (el.querySelector('#txt2img_prompt') || el.querySelector('#txt2img_neg_prompt'))) {

            return true;

        }

        return false;

    }



    function isGalleryBlock(el) {

        if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;

        var id = el.id || '';

        if (id === 'txt2img_gallery_container' || id === 'image_buttons_txt2img') return true;

        if (id === 'txt2img_generate_box') return true;

        if (el.querySelector && el.querySelector('#txt2img_gallery') && !el.querySelector('#html_info_txt2img')) {

            return !isPromptBlock(el);

        }

        return false;

    }



    function isInfoBlock(el) {

        if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;

        var id = el.id || '';

        if (id === 'html_info_txt2img' || id === 'html_log_txt2img') return true;

        if (el.querySelector && (el.querySelector('#html_info_txt2img') || el.querySelector('#html_log_txt2img'))) {

            return true;

        }

        if (el.classList && (el.classList.contains('infotext') || el.classList.contains('html-log'))) return true;

        return false;

    }



    function routeBlock(el, leftMount, rightMount) {

        if (isGalleryBlock(el)) {

            leftMount.appendChild(el);

            return;

        }

        if (isPromptBlock(el)) {

            return;

        }

        if (isInfoBlock(el)) {

            rightMount.appendChild(el);

            return;

        }

        if (el.querySelector && el.querySelector('#txt2img_gallery')) {

            leftMount.appendChild(el);

            return;

        }

        rightMount.appendChild(el);

    }



    function splitResultsPanel(panel, leftMount, rightMount) {

        while (panel.firstChild) {

            routeBlock(panel.firstChild, leftMount, rightMount);

        }

        if (panel.parentElement && !panel.childElementCount) {

            panel.remove();

        }

    }



    function movePromptContainerToPromptTab(root, promptMount) {

        var container = root.getElementById('txt2img_prompt_container');

        if (!container || !promptMount || promptMount.contains(container)) return;

        promptMount.appendChild(container);

        unhideElement(container);

    }



    function alreadySplit(leftMount, rightMount, promptMount) {

        return !!(leftMount.querySelector('#txt2img_gallery, #txt2img_gallery_container')

            && promptMount.querySelector('#txt2img_prompt, #txt2img_prompt_container')

            && rightMount.querySelector('#html_info_txt2img, .infotext'));

    }



    function prepareOutputLeftCol(leftMount) {

        if (leftMount) {

            leftMount.classList.add('progress-container');

        }

    }



    function moveOutputToMount() {

        var root = appRoot();

        var leftMount = findColMount(root, 'left');

        var rightMount = findColMount(root, 'right');

        var promptMount = findPromptMount(root);

        var results = findResultsPanel(root);

        if (!leftMount || !rightMount || !promptMount) return false;



        prepareOutputLeftCol(leftMount);

        movePromptContainerToPromptTab(root, promptMount);



        if (!results) {

            if (alreadySplit(leftMount, rightMount, promptMount)) {

                moved = true;

                unhideElement(leftMount);

                unhideElement(rightMount);

                unhideElement(promptMount);

                return true;

            }

            return false;

        }



        if (moved && alreadySplit(leftMount, rightMount, promptMount) && !results.parentElement) {

            return true;

        }



        while (results.firstChild) {

            var child = results.firstChild;

            if (child.id === 'txt2img_results_panel') {

                splitResultsPanel(child, leftMount, rightMount);

            } else {

                routeBlock(child, leftMount, rightMount);

            }

        }



        if (results.parentElement && !results.childElementCount) {

            results.remove();

        }



        movePromptContainerToPromptTab(root, promptMount);

        unhideElement(leftMount);

        unhideElement(rightMount);

        unhideElement(promptMount);

        moved = true;

        console.log('[Prompt Composer] txt2img: prompts→prompt tab, gallery→Output');

        return true;

    }



    function scheduleMove(delay) {

        if (debounceTimer) clearTimeout(debounceTimer);

        debounceTimer = setTimeout(function () {

            debounceTimer = null;

            if (moveOutputToMount()) {

                retryCount = 0;

                return;

            }

            if (retryCount < 120) {

                retryCount++;

                scheduleMove(350);

            }

        }, delay == null ? 150 : delay);

    }



    function watchDom() {

        try {

            var obs = new MutationObserver(function () {

                scheduleMove(200);

            });

            obs.observe(appRoot(), { childList: true, subtree: true });

        } catch (_) { /* ignore */ }

    }



    function init() {

        scheduleMove(500);

        watchDom();

        setInterval(function () {

            scheduleMove(500);

        }, 2500);

    }



    if (document.readyState === 'loading') {

        document.addEventListener('DOMContentLoaded', function () {

            setTimeout(init, 900);

        });

    } else {

        setTimeout(init, 900);

    }



    window.PcTxt2imgOutputMount = {

        sync: function () {

            moved = false;

            return moveOutputToMount();

        },

        isMoved: function () { return moved; }

    };

})();


