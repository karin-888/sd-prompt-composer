""" -*- coding: UTF-8 -*-
Prompt Composer - Illustrious対応プロンプト管理拡張
Main entry point for the WebUI extension.

Features:
  - Block-based Prompt Composer with Illustrious ordering
  - Asset Browser for LoRA/Embedding with Civitai Helper integration
  - Named preset save/load
"""

import os
import gradio as gr
import modules
from modules import scripts, script_callbacks

# Extension path
EXTENSION_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import our modules using relative import workaround
import importlib
import sys

# Add scripts dir to path for imports
_scripts_dir = os.path.join(EXTENSION_PATH, "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import civitai_reader
import asset_indexer
import preset_store
import order_profiles
import tag_dictionary
import tag_suggest
import api as composer_api
from modules import shared


def on_app_started(demo, app):
    """Register FastAPI endpoints when the app starts."""
    # Initialize modules
    asset_indexer.init(EXTENSION_PATH)
    preset_store.init(EXTENSION_PATH)
    order_profiles.init(EXTENSION_PATH)
    tag_dictionary.init(EXTENSION_PATH)
    tag_suggest.init(EXTENSION_PATH)
    import user_data
    user_data.init(EXTENSION_PATH)
    
    # Register API routes
    composer_api.register_api(app, EXTENSION_PATH)
    
    # Trigger initial asset scan in background
    print("[Prompt Composer] Extension loaded. Assets will be scanned on first request.")

def on_ui_settings():
    # Optional machine translation fallback for unknown manual tags
    shared.opts.add_option(
        "pc_deepl_enable",
        shared.OptionInfo(
            False,
            "Prompt Composer: Use DeepL for unknown manual tags",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_deepl_api_key",
        shared.OptionInfo(
            "",
            "Prompt Composer: DeepL API key (optional)",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_deepl_api_url",
        shared.OptionInfo(
            "https://api-free.deepl.com/v2/translate",
            "Prompt Composer: DeepL API URL",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )


def on_ui_tabs():
    """Create the Prompt Composer tab UI."""
    
    with gr.Blocks(analytics_enabled=False) as prompt_composer_tab:
        
        # Hidden state elements for JS communication
        with gr.Row(visible=False):
            js_state = gr.Textbox(
                elem_id="pc_js_state",
                value="",
                visible=False
            )
            py_result = gr.Textbox(
                elem_id="pc_py_result",
                value="",
                visible=False
            )
        
        with gr.Row(elem_id="pc_output_area", elem_classes="pc-output-area"):
            with gr.Column(scale=3):
                gr.HTML(
                    '<div class="pc-section-header">📝 Final Prompt</div>'
                    '<div id="pc_order_warning"></div>'
                )
                final_prompt = gr.Textbox(
                    elem_id="pc_final_prompt",
                    label="Prompt",
                    lines=3,
                    interactive=True,
                    placeholder="Prompt Composerでブロックを組み立てると、ここに最終プロンプトが生成されます..."
                )
                final_negative = gr.Textbox(
                    elem_id="pc_final_negative",
                    label="Negative Prompt",
                    lines=2,
                    interactive=True,
                    placeholder="Negativeブロックの内容が反映されます..."
                )
                gr.HTML(
                    '<div class="pc-tokenizer-header">'
                    'Tokenizer (簡易表示)'
                    '<button id="pc_tokenizer_button" class="pc-tokenizer-reload">トークン数を計算</button>'
                    '</div>'
                    '<div id="pc_tokenizer_view" class="pc-tokenizer-view">プロンプトを入力して「トークン数を計算」を押すと結果が表示されます。</div>'
                )
            with gr.Column(scale=1, min_width=200):
                gr.HTML('<div class="pc-section-header">🔄 同期</div>')
                apply_txt2img_btn = gr.Button(
                    "📤 txt2img に適用",
                    elem_id="pc_apply_txt2img",
                    variant="primary"
                )
                apply_img2img_btn = gr.Button(
                    "📤 img2img に適用",
                    elem_id="pc_apply_img2img"
                )
                copy_btn = gr.Button(
                    "📋 クリップボードにコピー",
                    elem_id="pc_copy_clipboard"
                )
                
                gr.HTML('<div style="margin-top:20px;"></div>')
                btn_auto_format = gr.Button(
                    "✨ 自動整形 (空除去・末尾寄せ)",
                    elem_id="pc_auto_format",
                    variant="secondary"
                )
        
        # ===== MAIN: 3-column layout =====
        with gr.Row(elem_id="pc_main_area"):
            
            # --- LEFT: Asset Browser ---
            with gr.Column(scale=1, min_width=280, elem_id="pc_asset_browser_col"):
                gr.HTML('<div class="pc-section-header">🎨 Asset Browser</div>')
                
                with gr.Row():
                    asset_search = gr.Textbox(
                        elem_id="pc_asset_search",
                        placeholder="検索...",
                        label="",
                        show_label=False,
                        scale=3
                    )
                    asset_rescan_btn = gr.Button(
                        "🔄",
                        elem_id="pc_asset_rescan",
                        scale=1,
                        min_width=40
                    )
                
                with gr.Row():
                    asset_type_filter = gr.Radio(
                        elem_id="pc_asset_type_filter",
                        choices=["All", "LoRA", "Embedding", "Favorites", "Recent"],
                        value="All",
                        label="",
                        show_label=False,
                        interactive=True
                    )
                
                asset_subfolder_filter = gr.Dropdown(
                    elem_id="pc_asset_subfolder",
                    label="フォルダ",
                    choices=["(すべて)"] + asset_indexer.get_subfolders(),
                    value="(すべて)",
                    interactive=True,
                    allow_custom_value=True
                )
                
                # Asset cards - rendered by JavaScript
                asset_gallery = gr.HTML(
                    elem_id="pc_asset_gallery",
                    value='<div id="pc_asset_cards" class="pc-asset-cards"><div class="pc-loading">読み込み中...</div></div>'
                )
                
                with gr.Row():
                    asset_load_more_btn = gr.Button(
                        "もっと読み込む",
                        elem_id="pc_asset_load_more",
                        visible=True
                    )
            
            # --- CENTER: Prompt Composer ---
            with gr.Column(scale=2, min_width=400, elem_id="pc_composer_col"):
                gr.HTML('<div class="pc-section-header">🧩 Prompt Composer</div>')
                
                # Composer blocks (JS) + action toolbar inside same scroll area (#pc_composer_area)
                # so the bar stays at the bottom of the list and does not overlap blocks in some Gradio layouts.
                composer_area = gr.HTML(
                    elem_id="pc_composer_area",
                    value=(
                        '<div class="pc-composer-body">'
                        '<div id="pc_blocks_container" class="pc-blocks-container"></div>'
                        '<div class="pc-composer-toolbar-actions" role="toolbar" aria-label="Prompt Composer actions">'
                        '<button type="button" id="pc_add_block" class="pc-toolbar-btn">➕ ブロック追加</button>'
                        '<button type="button" id="pc_sort_blocks" class="pc-toolbar-btn">📐 順序整形</button>'
                        '<button type="button" id="pc_clear_blocks" class="pc-toolbar-btn">🗑️ 全クリア</button>'
                        "</div></div>"
                    ),
                )
                
                # Special tokens were moved to Tag Dictionary quickbar
            
            # --- RIGHT: Order profile + Preset + Tag Dictionary ---
            # Order profile UI is mounted here (not in the top sync column) so it stacks with
            # Preset Manager and does not overlap it in tight / equal-height Gradio layouts.
            with gr.Column(scale=1, min_width=260, elem_id="pc_preset_col", elem_classes=["pc-preset-col-stack"]):
                gr.HTML(
                    '<div class="pc-order-profile-section">'
                    '<div class="pc-section-header pc-section-header-sub">📐 順序プロファイル</div>'
                    '<div id="pc_order_profile" class="pc-order-profile-slot"></div>'
                    "</div>"
                )
                gr.HTML('<div class="pc-section-header">💾 Preset Manager</div>')
                
                with gr.Row():
                    preset_name_input = gr.Textbox(
                        elem_id="pc_preset_name",
                        placeholder="プリセット名...",
                        label="",
                        show_label=False,
                        scale=3
                    )
                    preset_save_btn = gr.Button(
                        "💾",
                        elem_id="pc_preset_save",
                        scale=1,
                        min_width=40,
                        variant="primary"
                    )
                
                # Preset list - rendered by JavaScript
                preset_list = gr.HTML(
                    elem_id="pc_preset_list",
                    value='<div id="pc_presets_container" class="pc-preset-list"></div>'
                )

                # Tag Dictionary / Wildcards tabs (rendered client-side by javascript)
                with gr.Tabs(elem_id="pc_dict_tabs"):
                    with gr.TabItem("🏷️ Tag Dictionary"):
                        gr.HTML('<div id="pc_tag_path_label" class="pc-tag-path-label"></div>')
                        tag_search = gr.Textbox(
                            elem_id="pc_tag_search",
                            placeholder="タグ / 日本語で検索...",
                            label="",
                            show_label=False
                        )
                        tag_list = gr.HTML(
                            elem_id="pc_tag_list",
                            value='<div id="pc_tags_container" class="pc-tags-container"></div>'
                        )
                    with gr.TabItem("🪄 Wildcards"):
                        wc_search = gr.Textbox(
                            elem_id="pc_wc_search",
                            placeholder="Wildcards（.txt）を検索...",
                            label="",
                            show_label=False
                        )
                        wc_list = gr.HTML(
                            elem_id="pc_wc_list",
                            value='<div id="pc_wildcards_container" class="pc-wc-container"></div>'
                        )

        # --- Backend Events for UI Interactivity ---
        def update_subfolders(asset_type):
            type_map = {
                "All": None,
                "LoRA": "lora",
                "Embedding": "embedding",
                "Favorites": None,
                "Recent": None
            }
            internal_type = type_map.get(asset_type)
            subfolders = asset_indexer.get_subfolders(asset_type=internal_type)
            return gr.update(choices=["(すべて)"] + subfolders, value="(すべて)")
        
        asset_type_filter.change(
            fn=update_subfolders,
            inputs=[asset_type_filter],
            outputs=[asset_subfolder_filter]
        )

    # script_callbacks.ui_tabs_callback expects a list of (Blocks, title, elem_id)
    return [(prompt_composer_tab, "Prompt Composer", "prompt_composer")]


# Register callbacks
script_callbacks.on_app_started(on_app_started)
script_callbacks.on_ui_tabs(on_ui_tabs)
script_callbacks.on_ui_settings(on_ui_settings)
