# kuku-lu-mcp

`m.kuku.lu`（捨てメアド／メルアドぽいぽい）の使い捨てメールボックスを、MCP 経由で AI エージェントから
扱えるようにする stdio MCP サーバーです。**受信専用**（後述の制限を参照）。

MCP server for the Japanese disposable-mail service [m.kuku.lu](https://m.kuku.lu):
create throwaway addresses, wait for the verification mail, and hand the code/link
to the agent. Receive-only.

---

## なぜ自作なのか / Why this exists

- m.kuku.lu には公式 API も MCP サーバーも存在しません（2026-11 時点で Glama / Smithery /
  npm / PyPI を検索しても 0 件）。
- サイトは Cloudflare のボット判定配下にあり、素の `curl` では `Just a moment...` が返ります。
  ブラウザ相当のヘッダーを付けた HTTP クライアントなら通過します（本サーバーはそれで動きます）。
- 既存のコミュニティ製ラッパー（[zrpy/kukumail.py](https://github.com/zrpy/kukumail.py)、
  [taka-4602/m.kuku.lu-Generator](https://github.com/taka-4602/m.kuku.lu-Generator)、
  [@edamame-x/kukumailjs](https://jsr.io/@edamame-x/kukumailjs)）は 2026 年時点の画面と
  リクエスト仕様に追随できておらず（`csrf_subtoken_check` の廃止、送信が reCAPTCHA 必須化）、
  そのままでは動きません。本実装は現行の HTML/JS からエンドポイントを取り直したものです。

## できること / Capabilities

| 機能 | 状態 |
|---|---|
| アカウント（ID/パスワード）の永続化・再利用 | ✅ |
| アドレス自動作成 / ワンタイム / 名前・ドメイン指定 | ✅（71 ドメインから選択可） |
| 受信トレイ一覧・本文取得・ワンタイムコード抽出・リンク抽出 | ✅ |
| 新着メールの待機（ロングポーリング） | ✅ |
| アドレス削除 | ✅ |
| **メール送信** | ❌ reCAPTCHA 必須（自動化不可） |
| POP/IMAP/SMTP アクセス | ❌ この実装では `NG`（有料/条件付き） |

## インストール / Install

```sh
git clone https://github.com/yuchi0531/kuku-lu-mcp.git
cd kuku-lu-mcp
python3 -m venv .venv          # ensurepip が必要（Debian 系は python3-venv）
.venv/bin/pip install -e .
```

`PYTHONPATH` が他の環境を指していると依存解決が壊れるため、同梱の `run.sh` は
`PYTHONPATH` を消してから venv の python を起動します。

### Hermes Agent

```sh
hermes mcp add kuku-lu \
  --command /path/to/kuku-lu-mcp/run.sh \
  --env KUKULU_STATE_DIR=/path/to/kuku-lu-mcp/.state
hermes mcp test kuku-lu
```

### Claude Desktop / Cursor / その他 MCP クライアント

```json
{
  "mcpServers": {
    "kuku-lu": {
      "command": "/path/to/kuku-lu-mcp/run.sh",
      "env": { "KUKULU_STATE_DIR": "/path/to/kuku-lu-mcp/.state" }
    }
  }
}
```

## ツール / Tools

| ツール | 用途 |
|---|---|
| `kuku_create_address(kind="auto"\|"onetime"\|"custom", username?, domain?)` | アドレス作成。`onetime` は有効期限付き、`custom` は名前とドメイン指定 |
| `kuku_list_addresses()` | 保有アドレス一覧 |
| `kuku_list_domains()` | `custom` で選べるドメイン一覧 |
| `kuku_account()` | 永続化された ID / パスワード / 状態ファイル |
| `kuku_list_messages(address, limit=20)` | 受信一覧（メタデータのみ） |
| `kuku_read_message(address, number)` | 本文・コード・リンク |
| `kuku_wait_for_message(address, timeout_seconds=90, from_contains?, subject_contains?, read=true)` | 新着待機（フォーム送信直後に使う） |
| `kuku_delete_address(address, delete_mail=false)` | アドレス削除 |

典型的な流れ:

1. `kuku_create_address("auto")` → `abc@choco.la`
2. そのアドレスでサインアップフォームを送信
3. `kuku_wait_for_message(address, subject_contains="verify")` → `codes` / `links` / 本文
4. 不要になったら `kuku_delete_address(address)`

## CLI（デバッグ用）

```sh
.venv/bin/python -m kukulumcp.cli account
.venv/bin/python -m kukulumcp.cli create auto
.venv/bin/python -m kukulumcp.cli ls
.venv/bin/python -m kukulumcp.cli msgs <address>
.venv/bin/python -m kukulumcp.cli read <address> <number>
.venv/bin/python -m kukulumcp.cli wait <address> --timeout 90
```

## 制限と注意 / Limitations

- **受信専用**。送信フォーム（`/new.php` POST `sendMail`）は reCAPTCHA トークンを要求するため
  自動化できません。
- **IP 単位の制限**があり、セッション生成を繰り返すと弾かれます。本実装は 1 インストール =
  1 アカウントで状態をファイルに永続化し、以降はそのセッションハッシュを再利用します
  （`KUKULU_STATE_DIR`、既定 `~/.config/kuku-lu-mcp`）。
- Cloudflare の判定は IP に依存します。日本の住宅回線・モバイル回線では安定しますが、
  データセンター IP ではブロックされることがあります（その場合は `CloudflareBlocked` エラーを返します）。
- 捨てメアド判定を行うサービスでは拒否されることがあります。その用途では kuku.lu の
  ドメイン指定作成が有効な場合がありますが、規約と各サービスのポリシーに従って使用してください。
- 自分が管理する／テストする対象への利用を想定しています。第三者サービスの大量アカウント作成など
  迷惑行為には使わないでください。

## 検証済み / Verified

`tests/e2e.py` は実サービスに対して「アドレス作成 → 外部からの実メール受信（formsubmit.co の
アクティベーション通知）→ 待機 → 本文/コード/リンク取得 → 削除」までを通します。

```sh
KUKULU_STATE_DIR=.state .venv/bin/python -m tests.e2e
```

2026-11 時点の m.kuku.lu 本番環境で成功を確認済み（Hermes Agent の MCP クライアント経由でも同様）。

## 謝辞 / Credits

エンドポイントの調査にあたり、以下のコミュニティ実装を参考にしました（コードは流用せず、
現行仕様に合わせて書き直しています）。

- zrpy/kukumail.py (Python wrapper)
- taka-4602/m.kuku.lu-Generator (async Python)
- @edamame-x/kukumailjs (TypeScript)

## License

MIT
