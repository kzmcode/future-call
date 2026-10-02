# 未来の自分からの電話

体験者が自分の「失敗した体験」を声で語ると、しばらくして **10年後の自分から電話がかかってくる** 展示用Webアプリです。電話に出ると、体験者に似た声で「あの失敗は、実は未来へのきっかけだった」という物語が語られます。

- 非商用の展示・イベント向け / 日本語のみ / 全年齢(子どもを含む)
- パソコン1台(Mac 推奨)で動作。GPU 不要。ブラウザ(Chrome)で全画面表示
- 詳しい仕様は [`future_call_requirements.md`](future_call_requirements.md)、実装の取り決めは [`docs/architecture.md`](docs/architecture.md)

## 主な機能

| 機能 | 内容 |
|---|---|
| 録音 | 20〜90秒。音量メーター、やり直し、話し方のヒント表示 |
| 音声認識 | faster-whisper(ローカル、無料) |
| ストーリー生成 | ローカルの Ollama(既定)。失敗時は用意済みテンプレートで自動代替。Gemini API も選べます |
| 読み上げ・声の再現 | Chatterbox(ローカル・ゼロショット声クローン)。声も内容も端末の外に出ません([ローカル完結モード](docs/08_local_mode.md))。旧構成(Gemini TTS + OpenVoice)も選べます |
| 電話らしい台本 | 「えっとね」「あはは」などの間投詞・間を含む話し言葉。物語は「パート」に分かれ、着信までの時間を短縮 |
| 疑似的なやりとり | 問いかけ(「覚えてる?」)のあと、体験者の返事を少し待って続きを再生。マイクの音量だけを見て、録音・送信はしない |
| 環境音 | 通話中にカフェなどの生活音をかすかに流す(ブラウザで自動生成) |
| 電話演出 | 着信画面・着信音・電話音質エフェクト |
| 安全・プライバシー | 同意画面(v2 で「読み上げの声づくりにも Gemini を使う。送るのは文章だけで、声は送らない」旨を追記)、体験後のデータ自動削除、ログに内容を残さない、深刻な話題では寄り添う内容に切替 |
| 運用 | スタッフ用の隠しリセット(左上長押し)、ワンクリック起動、設定ファイル |

### v2 の音声の流れ

```
体験者の声 → 文字起こし(ローカル)→ Gemini で台本生成(文章のみ送信)
   → Gemini TTS で読み上げ(文章と話し方の指示のみ送信)→ OpenVoice で体験者の声色に変換
   → 電話音質 → パートごとに再生(問いかけのあとで返事待ち)+ 環境音
```

Gemini TTS には **google-genai 2.25 以上** が必要です(古いと自動で標準音声になります)。読み上げに Gemini を使わない場合は `tts.engine: openvoice` / `melo` にします([設定](docs/03_config.md))。

## クイックスタート

1. [セットアップ](docs/01_setup.md)(初回のみ)
2. [Gemini APIキーの取得と設定](docs/02_gemini_api.md)
3. [設定ファイルの確認](docs/03_config.md)
4. [マイク・スピーカーの準備](docs/04_audio_devices.md)
5. [起動](docs/05_kiosk_launch.md)

macOS の場合、最短は次のとおりです。

```bash
cd future-call
bash scripts/setup.sh          # 初回のみ。数分〜十数分かかります
# .env に GEMINI_API_KEY を書き込む(docs/02_gemini_api.md)
./scripts/start.command        # 起動(Finder からダブルクリックでも可)
```

## ドキュメント一覧

| ファイル | 対象 | 内容 |
|---|---|---|
| [docs/01_setup.md](docs/01_setup.md) | 準備担当 | インストール手順 |
| [docs/02_gemini_api.md](docs/02_gemini_api.md) | 準備担当 | APIキー取得、注意事項 |
| [docs/03_config.md](docs/03_config.md) | 準備担当 | config.yaml の全項目 |
| [docs/04_audio_devices.md](docs/04_audio_devices.md) | 準備担当 | マイク・スピーカー調整 |
| [docs/05_kiosk_launch.md](docs/05_kiosk_launch.md) | 準備・当日 | 起動と全画面運用 |
| [docs/06_operation_manual.md](docs/06_operation_manual.md) | 当日スタッフ | 運用マニュアル |
| [docs/07_troubleshooting.md](docs/07_troubleshooting.md) | 全員 | トラブル対処 |
| [docs/architecture.md](docs/architecture.md) | 開発者 | 設計・API契約 |

## ディレクトリ構成

```
future-call/
├── config.yaml              設定ファイル
├── .env                     APIキー(.env.example をコピーして作成。公開しない)
├── requirements.txt         軽量な依存ライブラリ
├── requirements-models.txt  重い依存(faster-whisper, MeloTTS, OpenVoice)
├── backend/app/             FastAPI サーバー本体
├── backend/tests/           自動テスト
├── frontend/                画面(HTML/CSS/JS、ビルド不要)
├── models/OpenVoiceV2/      声変換モデル(download_models.py が配置)
├── scripts/                 setup / start / download_models
├── logs/                    ログ(futurecall.log / server.out。処理時間とエラー種別のみ)
└── docs/                    マニュアル
```

## モックモード(開発・動作確認用)

重いモデルや API キーが無くても、画面の流れを確認できます。`config.yaml` を次のようにします。

```yaml
stt:
  engine: mock
tts:
  engine: mock
llm:
  engine: template
```

- `stt: mock` は固定の文章を認識結果として返し、`tts: mock` は簡易な音を生成します。`llm: template` は Gemini を使わずテンプレートの物語を使います。
- 本番では `faster_whisper` / `gemini_openvoice` / `gemini` に戻してください。

## テストの実行

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## 使用モデルとライセンスに関する注意

| 要素 | ライセンス(著者の知る範囲) |
|---|---|
| MeloTTS | MIT |
| OpenVoice V2 | MIT(V2 は商用利用も可とされています) |
| faster-whisper | MIT |
| Whisper のモデル重み | MIT |
| Gemini API(物語生成・Gemini TTS) | Google の利用規約(無料枠は入力がサービス改善に使われる場合あり) |

上記は執筆時点の理解です。ライセンスや規約は変更されることがあるため、**展示前に各配布元(GitHub / Hugging Face / Google)で最新の条件を必ず再確認してください**(要件 R-07)。

「声の再現」は本人に「似た声」になる技術で、そっくりにはなりません。展示の説明文でも「そっくり」ではなく「あなたに似た声」と表現してください。
