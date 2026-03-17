# Prompt Composer - Illustrious対応プロンプト管理拡張

Stable Diffusion WebUI (AUTOMATIC1111 / Forge / reForge) 用の拡張機能です。

## 対応

- AUTOMATIC1111 / Forge / reForge
- macOS / Windows / Linux（WebUIが動く環境）

## 機能

### 🧩 Prompt Composer
- ブロック単位でプロンプトを整理・構築
- ドラッグ＆ドロップでブロック並び替え
- トークンチップ表示・追加・削除
- Illustrious順序プロファイルに基づく自動整形

### 🎨 Asset Browser
- LoRA / Embedding を画像付きカードで一覧表示
- Civitai Helper の情報（サムネイル、トリガーワード）を自動読込
- テキスト検索、種別フィルタ、フォルダフィルタ
- カードクリックで Prompt Composer に挿入

### 💾 Preset Manager
- 名前を付けてプロンプト構成を保存
- 読込・上書き・削除
- 保存内容: 全ブロック + Negative + 順序プロファイル

### 📐 Illustrious 順序プロファイル
- Illustrious標準 / キャラ重視 / 背景重視
- ワンクリックでブロック順序を整形

## インストール

### GitHub から入れる（推奨）

WebUI のルートで実行します。

```bash
cd extensions
git clone <このリポジトリのURL> sd-prompt-composer
```

その後、WebUI を再起動して、ブラウザをハードリロードしてください（`Cmd/Ctrl+Shift+R`）。

### 手動（zip 展開など）

1. WebUI の `extensions/` フォルダに `sd-prompt-composer/` を配置
2. WebUI を再起動
3. ブラウザをハードリロード
4. 「Prompt Composer」タブが表示されます

## 依存（あると便利 / 任意）

### a1111-sd-webui-tagcomplete（タグ補完の辞書）

この拡張の **タグサジェスト** は、次の優先順でCSVを読みます。

1. `extensions/a1111-sd-webui-tagcomplete/tags/*.csv`（見つかればこちらを優先）
2. `extensions/sd-prompt-composer/tags/*.csv`（ローカル同梱分）

巨大CSVをこの拡張に同梱しなくても動くようにしているため、**tagcomplete を入れておくのが推奨**です。

### sd-webui-prompt-aio-enhanced（タグ辞書UI）

Tag Dictionary は、次の優先順でYAMLを読みます。

1. `extensions/sd-prompt-composer/group_tags/default.yaml`（この拡張に同梱）
2. `extensions/sd-webui-prompt-aio-enhanced/group_tags/default.yaml`（従来の互換）

未導入でも拡張は動作します。

## 使い方

1. **Asset Browser** で LoRA / Embedding を検索・クリック挿入
2. **Prompt Composer** でブロックごとにタグを編集
3. **順序プロファイル** を選択して並びを整形
4. **txt2img / img2img に適用** で WebUI に反映
5. **Preset Manager** で構成を保存・再利用

## トラブルシュート

### 「txt2img に適用」「img2img に適用」ボタンが効かない

- WebUI再起動後、**ブラウザをハードリロード**してください（`Cmd/Ctrl+Shift+R`）
- それでもダメなら、ブラウザの開発者ツール Console を開き、`[Prompt Composer]` のログ/エラーを確認してください

### タグサジェストが出ない

- `a1111-sd-webui-tagcomplete` が入っているか確認してください（入っていない場合はサジェストが空になりやすいです）

