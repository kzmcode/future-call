# 05. 起動とキオスク(全画面)運用

## 1. 起動スクリプト(F-64)

| OS | ファイル | 使い方 |
|---|---|---|
| macOS | `scripts/start.command` | Finder でダブルクリック。初回は右クリック →「開く」 |
| macOS / Linux | `scripts/start.sh` | ターミナルで `bash scripts/start.sh` |
| Windows | `scripts/start.bat` | ダブルクリック |

macOS で「実行権限がない」と出たら次を一度だけ実行します。

```bash
chmod +x scripts/start.command scripts/start.sh
```

スクリプトは (1) サーバーを起動し、(2) 準備ができるのを待ち、(3) Chrome を全画面(キオスクモード)で開きます。起動直後はモデルの読み込みで **1〜2 分ほど「準備中」** になることがあります。

## 2. キオスクモードの意味

Chrome を次のオプションで開いています(`scripts/start.sh` と `scripts/start.bat` で同じ内容です)。

| オプション | 効果 |
|---|---|
| `--kiosk` | アドレスバーなしの全画面 |
| `--autoplay-policy=no-user-gesture-required` | 着信音を操作なしで鳴らせる |
| `--use-fake-ui-for-media-stream` | マイク許可の確認ダイアログを省略 |
| `--user-data-dir=<リポジトリ>/.chrome-profile` | 専用プロファイルを使い、通常の Chrome と設定を分ける |
| `--no-first-run` | 初回起動のウェルカム画面を出さない |
| `--no-default-browser-check` | 既定ブラウザ確認を出さない |
| `--disable-session-crashed-bubble` | 「正しく終了しませんでした」の表示を出さない |
| `--disable-infobars` | 情報バーを出さない |
| `--disable-pinch` | ピンチ操作による拡大縮小を無効にする |
| `--overscroll-history-navigation=0` | スワイプによる「戻る/進む」を無効にする |

上記が `scripts/start.*` の実際の内容です。オプションを変えたときはこの表も更新してください。

## 3. 終了方法

- macOS: `Cmd + Q` で Chrome を終了。サーバーを動かしているターミナルで `Ctrl + C`(またはウィンドウを閉じる)
- Windows: `Alt + F4`、サーバーのウィンドウも閉じる
- フリーズしたとき: 画面左上を 3 秒長押し(スタッフ用リセット)で待機画面に戻ります

## 4. スリープ防止

長時間の展示では、画面やシステムが眠らないようにします。

- macOS「システム設定」→「ディスプレイ」/「バッテリー(または省エネルギー)」で、ディスプレイをオフにする時間を「しない」、電源アダプタ接続時のスリープを防止に設定
- スクリプトで防ぐ場合(別のターミナルで): `caffeinate -dimsu`(止めるには `Ctrl + C`)
- スクリーンセーバー・自動ロックをオフにする
- Windows: 「設定」→「システム」→「電源」で画面とスリープを「なし」

## 5. 自動ログイン・自動起動(任意)

停電後などに自動で復旧させたい場合に設定します。

- macOS: 「システム設定」→「ユーザとグループ」→「自動ログイン」で有効化。「ログイン項目」に `start.command` を追加
- Windows: `Win + R` → `shell:startup` を開き、`start.bat` のショートカットを入れる

自動ログインはセキュリティ上のリスクがあるため、会場の管理下でのみ使い、展示後に戻してください。

## 6. Chrome の自動再生とマイク許可

- **マイク**: 初回は許可の表示が出ます。「許可」を選んでください。誤って「ブロック」した場合は `chrome://settings/content/microphone` で `localhost` を許可に戻します。
- **自動再生**: 着信音を鳴らすには、キオスク起動オプションか、`chrome://settings/content/sound` で `localhost` を「許可」にします。
- **マイクの選択**: 複数のマイクがあると別のものが選ばれることがあります([04](04_audio_devices.md))。
