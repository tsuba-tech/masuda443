# MASUDA 443

Version: `v1.0.0`

東京ヤクルトスワローズ・増田珠選手の規定打席443到達および首位打者争いを追跡する、非公式ファンサイトです。

「規定までの残り打席」「現在の首位打者との差」「規定未到達時の首位打者特例」「直近5・10試合」を自動更新し、増田選手の状態に合わせて画面テーマと応援メッセージが変わります。

## ローカルで表示

```bash
python -m pip install -r requirements.txt
python update.py
python -m http.server 8000
```

ブラウザで `http://localhost:8000/` を開きます。`file://` で直接開くとブラウザの制限により `data.json` を取得できないため、ローカルHTTPサーバーを使用してください。

## データ更新

```bash
python update.py
```

`update.py` は [baseballdata.jp](https://baseballdata.jp/) から次のページを取得します。

- セ・リーグ規定打席未到達ランキング（増田選手のシーズン成績）
- セ・リーグ規定打席ランキング（首位打者）
- 増田選手の全打席成績（直近5・10試合、連続安打など）

実行前に `robots.txt` を確認し、対象パスが禁止されていれば停止します。現時点の指定は `User-agent: *` / `Allow: /` です。列番号ではなく日本語の列見出しと選手名を基準に解析します。取得・解析・検証のいずれかに失敗した場合はエラー終了し、既存の `data.json` は変更しません。打率は安打数÷打数で再計算し、掲載値との差も検証します。

取得は必要な3ページだけに限定し、User-Agentを明示します。通信エラー時の再試行は3秒空けて1回だけ、403・429では再試行しません。元ページのHTMLは保存せず、抽出した数値だけを公開します。

外部取得を停止する場合は環境変数を設定します。この場合、`data.json` はそのまま保持されます。

```bash
SCRAPING_ENABLED=false python update.py
```

Windows PowerShellでは `$env:SCRAPING_ENABLED='false'; python update.py` とします。User-Agentの連絡先URLは `MASUDA443_USER_AGENT` 環境変数でリポジトリURL等に変更できます。

正常取得時刻は `data.json` の `last_successful_fetch` に保存します。取得失敗時は `data.json` に触れず、`fetch-status.json` だけをエラー状態にするため、画面には前回正常取得データを残したまま注意表示が出ます。

## GitHub Actions

`.github/workflows/update.yml` は毎日、日本時間21:30・22:30・23:30に更新を実行します。Actions画面の `Run workflow` から手動実行もできます。データに差分がある場合だけコミットし、処理後に最新のサイトをGitHub Pagesへ公開します。

リポジトリの **Settings → Actions → General → Workflow permissions** で書き込み権限を許可してください。ワークフロー側にも `contents: write` を設定済みです。

## GitHub Pages

1. GitHubにこのディレクトリをリポジトリとしてpushします。
2. **Settings → Pages** を開きます。
3. Sourceを **GitHub Actions** にします。
4. `.github/workflows/pages.yml` が、`main` への通常のpush時にサイトを公開します。

公開URLは通常 `https://<username>.github.io/masuda443/` です。定期データ更新後も `update.yml` 内の公開ジョブが実行されるため、最新の `data.json` がサイトへ反映されます。

## ファイル構成

```text
masuda443/
├── VERSION                     # 現在のリリースバージョン
├── index.html                  # 画面構造
├── style.css                  # 状態別テーマとレスポンシブ表示
├── app.js                     # 表示・シミュレーター・応援ボタン
├── data.json                  # 自動生成される表示データ
├── fetch-status.json          # 最新の取得成否（成績データとは分離）
├── update.py                  # 取得・計算・検証・安全な書き込み
├── requirements.txt
├── tests/
│   └── test_logic.py          # 規定打席・特例・状態判定テスト
└── .github/workflows/
    ├── update.yml             # 定期データ更新と更新後の公開
    └── pages.yml              # 通常のpush時のサイト公開
```

## 注意事項

本サイトは非公式ファンサイトです。東京ヤクルトスワローズ、NPB、選手本人とは関係ありません。公式ロゴ、公式画像、選手写真は使用していません。データの利用・公開にあたっては取得元サイトの方針や負荷に配慮してください。
