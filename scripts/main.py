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
from modules import script_callbacks

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
import ips_data_loader
import ips_collections_store
import api as composer_api
import image_caption
from modules import shared, ui_components


def _prompt_dictionary_installed() -> bool:
    ext_root = os.path.dirname(EXTENSION_PATH)
    return os.path.isfile(
        os.path.join(ext_root, "sd-webui-prompt-dictionary", "scripts", "prompt_dictionary.py")
    )


def _embed_prompt_dictionary_ui() -> bool:
    if not _prompt_dictionary_installed():
        return False
    try:
        ext_root = os.path.dirname(EXTENSION_PATH)
        script_path = os.path.join(
            ext_root, "sd-webui-prompt-dictionary", "scripts", "prompt_dictionary.py"
        )
        mod_name = "sd_webui_prompt_dictionary_pc_embed"
        pd_mod = sys.modules.get(mod_name)
        if pd_mod is None:
            spec = importlib.util.spec_from_file_location(mod_name, script_path)
            if spec is None or spec.loader is None:
                return False
            pd_mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = pd_mod
            spec.loader.exec_module(pd_mod)

        return bool(pd_mod.build_prompt_dictionary_ui())
    except Exception as exc:
        print(f"[Prompt Composer] Prompt Dictionary embed failed: {exc}")
        return False


def on_before_reload():
    print("[Prompt Composer] Reload UI: rebuilding interface (may take 30–60s with large LoRA libraries)...")


def on_app_started(demo, app):
    """Register FastAPI endpoints when the app starts."""
    # Initialize modules (idempotent; safe across Reload UI)
    asset_indexer.init(EXTENSION_PATH)
    preset_store.init(EXTENSION_PATH)
    order_profiles.init(EXTENSION_PATH)
    tag_dictionary.init(EXTENSION_PATH)
    tag_suggest.init(EXTENSION_PATH)
    ips_data_loader.init(EXTENSION_PATH)
    ips_collections_store.init(EXTENSION_PATH)
    import user_data
    user_data.init(EXTENSION_PATH)

    block_path = ips_collections_store.storage_path()
    preset_path = preset_store.storage_path()
    if block_path:
        print(f"[Prompt Composer] Block saves (per-column): {block_path}")
    if preset_path:
        print(f"[Prompt Composer] Presets (Preset Manager): {preset_path}")
    
    # Register API routes
    composer_api.register_api(app, EXTENSION_PATH)
    
    # Trigger initial asset scan in background
    print("[Prompt Composer] Extension loaded. Assets will be scanned on first request.")

def on_ui_settings():
    # Optional machine translation fallback for unknown manual tags
    shared.opts.add_option(
        "pc_argos_enable",
        shared.OptionInfo(
            False,
            "Prompt Composer: Use Argos Translate (無料・ローカル) for unknown tags",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_libre_enable",
        shared.OptionInfo(
            True,
            "Prompt Composer: Use LibreTranslate API (無料運用可) for unknown tags",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_libre_api_url",
        shared.OptionInfo(
            "http://127.0.0.1:5001/translate",
            "Prompt Composer: LibreTranslate API URL（自前サーバー推奨）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_libre_api_key",
        shared.OptionInfo(
            "",
            "Prompt Composer: LibreTranslate API key（必要なサーバーのみ）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )

    # Paid providers (optional, lower priority than free providers)
    shared.opts.add_option(
        "pc_deepl_enable",
        shared.OptionInfo(
            False,
            "Prompt Composer: Use DeepL for unknown tags (free providers fail時の有料フォールバック)",
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
    shared.opts.add_option(
        "pc_google_translate_enable",
        shared.OptionInfo(
            False,
            "Prompt Composer: Use Google Cloud Translation API for unknown tags (最終フォールバック・有料)",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_google_translate_api_key",
        shared.OptionInfo(
            "",
            "Prompt Composer: Google Cloud Translation API キー（GCPでCloud Translationを有効化し、キーを発行）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_google_translate_api_url",
        shared.OptionInfo(
            "https://translation.googleapis.com/language/translate/v2",
            "Prompt Composer: Google Translation REST のベースURL（通常は変更不要）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )

    shared.opts.add_option(
        "pc_vision_ollama_url",
        shared.OptionInfo(
            "http://127.0.0.1:11434",
            "Prompt Composer Vision: Ollama API URL（ローカル・無料）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_vision_gemini_api_key",
        shared.OptionInfo(
            "",
            "Prompt Composer Vision: Gemini API キー（任意・無料枠あり）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_vision_gemini_model",
        shared.OptionInfo(
            "gemini-2.0-flash",
            "Prompt Composer Vision: Gemini モデル（画像対応）",
            gr.Dropdown,
            image_caption.gemini_vision_model_dropdown_args,
            refresh=image_caption.refresh_gemini_vision_models,
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_vision_openai_api_key",
        shared.OptionInfo(
            "",
            "Prompt Composer Vision: OpenAI API キー（platform.openai.com の Secret key・sk- 始まり。ChatGPT Plus 課金とは別）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )
    shared.opts.add_option(
        "pc_vision_openai_model",
        shared.OptionInfo(
            "gpt-4o-mini",
            "Prompt Composer Vision: OpenAI モデル（画像対応）",
            ui_components.DropdownEditable,
            image_caption.openai_vision_model_dropdown_args,
            refresh=image_caption.refresh_openai_vision_models,
            section=("prompt_composer", "Prompt Composer"),
        ).info("🔄 で API から一覧取得（要 API キー）。リストに無い ID は手入力可。"),
    )
    shared.opts.add_option(
        "pc_vision_ollama_model",
        shared.OptionInfo(
            "llava",
            "Prompt Composer Vision: Ollama ビジョンモデル（画像対応）",
            ui_components.DropdownEditable,
            image_caption.ollama_vision_model_dropdown_args,
            refresh=image_caption.refresh_ollama_vision_models,
            section=("prompt_composer", "Prompt Composer"),
        ).info("Ollama 起動中に 🔄 でローカル一覧を取得。llava / moondream など。"),
    )
    shared.opts.add_option(
        "pc_vision_openai_api_url",
        shared.OptionInfo(
            "https://api.openai.com/v1",
            "Prompt Composer Vision: OpenAI API ベースURL（互換 API 用）",
            section=("prompt_composer", "Prompt Composer"),
        ),
    )


def on_ui_tabs():
    """Create the Prompt Composer tab UI."""
    print("[Prompt Composer] Building tab UI...")
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
        
        with gr.Tabs(elem_id="pc_workspace_tabs"):
            with gr.TabItem("🧩 プロンプト編集", id="pc_workspace_edit"):
                _build_prompt_editor_workspace()
            with gr.TabItem("📷 画像→文章", id="pc_workspace_vision"):
                _build_image_vision_workspace()

    # script_callbacks.ui_tabs_callback expects a list of (Blocks, title, elem_id)
    print("[Prompt Composer] Tab UI blocks ready.")
    return [(prompt_composer_tab, "Prompt Composer", "prompt_composer")]


def _build_prompt_editor_workspace():
    """Main block editor + asset browser (existing layout)."""
    with gr.Row(elem_id="pc_output_area", elem_classes="pc-output-area"):
            with gr.Column(scale=3, elem_classes=["pc-output-tabs-col"]):
                with gr.Tabs(elem_id="pc_final_prompt_tabs"):
                    with gr.TabItem("prompt", id="pc_final_tab_1"):
                        gr.HTML(
                            '<div class="pc-section-header">📝 Final Prompt</div>'
                            '<div id="pc_order_warning"></div>'
                        )
                        with gr.Column(
                            elem_id="pc_prompt_tab_prompt_mount",
                            elem_classes=["pc-prompt-tab-prompt-mount"],
                        ):
                            pass
                        final_prompt = gr.Textbox(
                            elem_id="pc_final_prompt",
                            label="Prompt",
                            lines=3,
                            interactive=True,
                            visible=False,
                            placeholder="Prompt Composerでブロックを組み立てると、ここに最終プロンプトが生成されます..."
                        )
                        final_negative = gr.Textbox(
                            elem_id="pc_final_negative",
                            label="Negative Prompt",
                            lines=2,
                            interactive=True,
                            visible=False,
                            placeholder="Negativeブロックの内容が反映されます..."
                        )
                        gr.HTML(
                            '<div class="pc-tokenizer-header">'
                            'Tokenizer (簡易表示)'
                            '<button id="pc_tokenizer_button" class="pc-tokenizer-reload">トークン数を計算</button>'
                            '</div>'
                            '<div id="pc_tokenizer_view" class="pc-tokenizer-view">'
                            'Positive / Negative それぞれのトークン数を表示します。'
                            'プロンプトを入力して「トークン数を計算」を押してください。'
                            '</div>'
                        )
                    with gr.TabItem("Generation", id="pc_final_tab_2"):
                        with gr.Row(
                            elem_id="pc_generation_two_col",
                            elem_classes=["pc-generation-two-col"],
                        ):
                            with gr.Column(
                                elem_id="pc_txt2img_settings_col_left",
                                elem_classes=["pc-txt2img-settings-col"],
                                scale=1,
                                min_width=280,
                            ):
                                pass
                            with gr.Column(
                                elem_id="pc_txt2img_settings_col_right",
                                elem_classes=["pc-txt2img-settings-col"],
                                scale=1,
                                min_width=280,
                            ):
                                pass
                    with gr.TabItem("Output", id="pc_final_tab_output"):
                        with gr.Row(
                            elem_id="pc_output_two_col",
                            elem_classes=["pc-output-two-col"],
                        ):
                            with gr.Column(
                                elem_id="pc_txt2img_output_col_left",
                                elem_classes=["pc-txt2img-output-col"],
                                scale=1,
                                min_width=320,
                            ):
                                pass
                            with gr.Column(
                                elem_id="pc_txt2img_output_col_right",
                                elem_classes=["pc-txt2img-output-col"],
                                scale=1,
                                min_width=280,
                            ):
                                pass
            with gr.Column(scale=1, min_width=200, elem_classes=["pc-generate-actions-col"]):
                gr.HTML('<div class="pc-section-header">🎨 生成</div>')
                gr.HTML(
                    '<div id="pc_generate_live_preview" class="pc-generate-live-preview-host" aria-hidden="true"></div>'
                )
                generate_txt2img_btn = gr.Button(
                    "🎨 生成 (txt2img)",
                    elem_id="pc_generate_txt2img",
                    variant="primary",
                )
                gr.HTML(
                    '<div id="pc_generate_forever_mount" class="pc-generate-forever-slot"></div>'
                )
                gr.HTML('<div style="margin-top:14px;"></div>')
                gr.HTML('<div class="pc-section-header">🔄 同期</div>')
                apply_txt2img_btn = gr.Button(
                    "📤 txt2img に適用",
                    elem_id="pc_apply_txt2img",
                    variant="secondary"
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
                    choices=["Checkpoint", "LoRA", "Embedding", "Favorites"],
                    value="LoRA",
                    label="",
                    show_label=False,
                    interactive=True
                )
            
            def _initial_subfolder_choices():
                subfolders = asset_indexer.get_subfolders(
                    asset_type="lora",
                    allow_full_scan=False,
                )
                if not subfolders:
                    subfolders = asset_indexer.get_subfolders(
                        asset_type="lora",
                        allow_full_scan=True,
                    )
                return ["(すべて)"] + subfolders

            asset_subfolder_filter = gr.Dropdown(
                elem_id="pc_asset_subfolder",
                label="フォルダ",
                choices=_initial_subfolder_choices(),
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
            
            # Toolbar above blocks (same #pc_composer_area scroll) so actions stay clear of the
            # WebUI footer / version line that can overlap the lower part of long block lists.
            composer_area = gr.HTML(
                elem_id="pc_composer_area",
                value=(
                    '<div class="pc-composer-body">'
                    '<div class="pc-composer-toolbar-actions" role="toolbar" aria-label="Prompt Composer actions">'
                    '<button type="button" id="pc_add_block" class="pc-toolbar-btn">➕ ブロック追加</button>'
                    '<button type="button" id="pc_sort_blocks" class="pc-toolbar-btn">📐 順序整形</button>'
                    '<button type="button" id="pc_clear_blocks" class="pc-toolbar-btn">🗑️ 全クリア</button>'
                    '</div>'
                    '<div id="pc_blocks_container" class="pc-blocks-container"></div>'
                    "</div>"
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

            # Tag Dictionary / プロンプト大辞典 / Wildcards
            with gr.Tabs(elem_id="pc_dict_tabs"):
                with gr.TabItem("🏷️ Tag Dictionary", id="pc_dict_tab_tags"):
                    tag_search = gr.Textbox(
                        elem_id="pc_tag_search",
                        placeholder="タグ / 日本語で検索...",
                        label="",
                        show_label=False,
                    )
                    gr.HTML('<div id="pc_tag_path_label" class="pc-tag-path-label"></div>')
                    tag_list = gr.HTML(
                        elem_id="pc_tag_list",
                        value='<div id="pc_tags_container" class="pc-tags-container"></div>',
                    )
                with gr.TabItem("📖 プロンプト大辞典", id="pc_dict_tab_prompt_dictionary"):
                    if _prompt_dictionary_installed():
                        _embed_prompt_dictionary_ui()
                    else:
                        gr.HTML(
                            '<div class="pc-pd-missing">'
                            'sd-webui-prompt-dictionary 拡張が見つかりません。'
                            '</div>'
                        )
                with gr.TabItem("🪄 Wildcards", id="pc_dict_tab_wildcards"):
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
            "Checkpoint": "checkpoint",
            "LoRA": "lora",
            "Embedding": "embedding",
            "Favorites": None,
        }
        internal_type = type_map.get(asset_type)
        subfolders = asset_indexer.get_subfolders(asset_type=internal_type)
        return gr.update(choices=["(すべて)"] + subfolders, value="(すべて)")
        
    asset_type_filter.change(
        fn=update_subfolders,
        inputs=[asset_type_filter],
        outputs=[asset_subfolder_filter]
    )


def _build_image_vision_workspace():
    """Reference image → natural language / tags for Prompt Composer blocks."""
    gr.HTML(
        '<div class="pc-section-header">📷 参照画像 → プロンプト文章</div>'
        '<p class="pc-vision-intro">'
        '他の画像から服装・外見などを AI で書き出し、ブロックに反映できます。'
        ' BLIP は無料・ローカル（精度は一般的）。'
        ' 衣装の細部には ChatGPT / Gemini（API）または Ollama（ローカル）を推奨。'
        '</p>'
    )

    with gr.Row(elem_id="pc_vision_main_row", elem_classes=["pc-vision-main-row"]):
        with gr.Column(scale=1, min_width=320, elem_classes=["pc-vision-input-col"]):
            vision_image = gr.Image(
                elem_id="pc_vision_image",
                label="参照画像",
                type="pil",
                image_mode="RGB",
                sources=["upload", "clipboard"],
                height=420,
            )
            vision_focus = gr.Dropdown(
                elem_id="pc_vision_focus",
                label="抽出する内容",
                choices=list(image_caption._FOCUS_FROM_LABEL.keys()),
                value="👗 衣装・小物のみ",
            )
            with gr.Row():
                vision_provider = gr.Dropdown(
                    elem_id="pc_vision_provider",
                    label="AI",
                    choices=list(image_caption._PROVIDER_FROM_LABEL.keys()),
                    value="BLIP（ローカル・無料）",
                    scale=2,
                )
                vision_language = gr.Dropdown(
                    elem_id="pc_vision_language",
                    label="出力言語",
                    choices=list(image_caption._LANGUAGE_FROM_LABEL.keys()),
                    value="English（推奨）",
                    scale=1,
                )
            vision_output_style = gr.Dropdown(
                elem_id="pc_vision_output_style",
                label="出力形式",
                choices=list(image_caption._STYLE_FROM_LABEL.keys()),
                value="📝 詳細プロンプト（推奨）",
            )
            vision_analyze_btn = gr.Button(
                "🔍 画像を解析",
                elem_id="pc_vision_analyze",
                variant="primary",
            )
            vision_status = gr.HTML(
                elem_id="pc_vision_status",
                value='<span class="pc-vision-status">画像を選んで「画像を解析」を押してください。</span>',
            )

        with gr.Column(scale=1, min_width=360, elem_classes=["pc-vision-result-col"]):
            with gr.Row(elem_classes=["pc-vision-result-actions"]):
                vision_split_btn = gr.Button(
                    "🏷️ カンマで整理",
                    elem_id="pc_vision_split",
                    variant="secondary",
                    scale=1,
                )
                vision_auto_split = gr.Checkbox(
                    elem_id="pc_vision_auto_split",
                    label="ブロックへ送るときカンマで分割",
                    value=True,
                    scale=2,
                )
            vision_result = gr.Textbox(
                elem_id="pc_vision_result",
                label="生成されたプロンプト（詳細形式＝カンマ区切りフレーズ）",
                lines=12,
                placeholder="(white_dress:1.2), long_sleeves, lace_trim, ... のような形式で出力されます。",
                interactive=True,
            )
            vision_tags_preview = gr.HTML(
                elem_id="pc_vision_tags_preview_host",
                value=(
                    '<div id="pc_vision_tags_preview" class="pc-vision-tags-preview">'
                    '<span class="pc-vision-tags-empty">「カンマで整理」でフレーズ一覧を表示</span>'
                    "</div>"
                ),
            )
            gr.HTML('<div class="pc-section-header pc-section-header-sub">ブロックへ反映</div>')
            with gr.Row(elem_classes=["pc-vision-apply-row"]):
                vision_apply_outfit = gr.Button(
                    "👗 衣装ブロックへ",
                    elem_id="pc_vision_apply_outfit",
                    variant="secondary",
                )
                vision_apply_appearance = gr.Button(
                    "✨ 外見ブロックへ",
                    elem_id="pc_vision_apply_appearance",
                    variant="secondary",
                )
                vision_apply_character = gr.Button(
                    "👤 キャラブロックへ",
                    elem_id="pc_vision_apply_character",
                    variant="secondary",
                )
            with gr.Row(elem_classes=["pc-vision-apply-row"]):
                vision_apply_background = gr.Button(
                    "🌄 背景ブロックへ",
                    elem_id="pc_vision_apply_background",
                    variant="secondary",
                )
                vision_apply_replace = gr.Checkbox(
                    elem_id="pc_vision_apply_replace",
                    label="既存タグを置換（オフ＝追加）",
                    value=False,
                )
            vision_switch_edit_btn = gr.Button(
                "🧩 プロンプト編集タブへ移動",
                elem_id="pc_vision_switch_edit",
                variant="secondary",
            )

    def _vision_after_analyze(image, focus, provider, language, output_style):
        text, status = image_caption.analyze_reference_image(
            image, focus, provider, language, output_style
        )
        style = image_caption.normalize_output_style(output_style)
        if text and style == "simple":
            formatted = image_caption.format_tags_comma(text, style)
        else:
            formatted = (text or "").strip()
        preview = image_caption.format_tags_preview_html(formatted or text, style)
        return formatted or text, status, preview

    vision_analyze_btn.click(
        fn=_vision_after_analyze,
        inputs=[
            vision_image,
            vision_focus,
            vision_provider,
            vision_language,
            vision_output_style,
        ],
        outputs=[vision_result, vision_status, vision_tags_preview],
    )

    def _vision_split_and_preview(text, output_style):
        style = image_caption.normalize_output_style(output_style)
        formatted = image_caption.format_tags_comma(text, style)
        preview = image_caption.format_tags_preview_html(formatted, style)
        return formatted, preview

    vision_split_btn.click(
        fn=_vision_split_and_preview,
        inputs=[vision_result, vision_output_style],
        outputs=[vision_result, vision_tags_preview],
    )

    vision_result.change(
        fn=image_caption.format_tags_preview_html,
        inputs=[vision_result, vision_output_style],
        outputs=[vision_tags_preview],
    )


# Register callbacks
script_callbacks.on_before_reload(on_before_reload)
script_callbacks.on_app_started(on_app_started)
script_callbacks.on_ui_tabs(on_ui_tabs)
script_callbacks.on_ui_settings(on_ui_settings)
