# 08. ローカル完結モード(Chatterbox + Ollama)

既定の構成です。**体験者の声・話した内容・生成した台本・合成音声は、すべてこの Mac の中だけで処理され、外部に送信されません。** インターネットが必要なのは、セットアップ時のモデル取得だけです。子どもの体験者にも、外部サービスの規約を気にせず使えます。

| 処理 | 使うもの | 場所 |
|---|---|---|
| 文字起こし | faster-whisper | ローカル |
| 台本生成 | Ollama(既定 `gemma3:12b`) | ローカル(`127.0.0.1:11434`) |
| 声クローン + 読み上げ | Chatterbox Multilingual(参照音声だけでゼロショット) | ローカル(Apple Silicon は MPS) |

## セットアップ(Apple Silicon Mac)

```bash
brew install ollama uv     # 未導入なら
scripts/setup.sh           # Python 3.11 の .venv、Chatterbox、faster-whisper、Ollama モデルを取得
```

`setup.sh` は `ollama pull` も実行します。失敗した場合は Ollama アプリを起動して `ollama pull gemma3:12b` を実行してください。
起動前に Ollama を動かしておきます(アプリ、または `ollama serve`)。

## 設定(config.yaml)

```yaml
llm:  { engine: ollama, model: gemma3:12b, timeout_sec: 60 }
tts:  { engine: chatterbox, device: auto, chatterbox: { exaggeration: 0.5, cfg_weight: 0.5 } }
```

- `device: cpu` が既定です。M5 Mac での実測では、CPU は音声の約 3 倍の時間で安定して合成でき、MPS(Mac の GPU)は文ごとに遅くなり不安定でした(原因は未解明)。`mps` / `auto` も選べます。
- 台本の生成に失敗・タイムアウトしたとき、Ollama が動いていないときは、テンプレートの台本に自動で切り替わります。
- 声が似ないとき: `cfg_weight` を 0.3 前後へ。表現が弱いとき: `exaggeration` を上げる(0.7 など)。
- 合成が無音・極端に短い/長いときは、`max_retries` 回まで自動で再生成します。
- 生成音声には Chatterbox の PerTh 透かし(聞こえない電子透かし)が入ります。

## クラウドの構成に戻す

`llm.engine: gemini`(要 `.env` の `GEMINI_API_KEY`)、`tts.engine: gemini_openvoice` / `openvoice` / `melo` は従来どおり使えます。
その場合は旧依存(`requirements-models.txt`)を別の環境に入れてください。Chatterbox とは torch のバージョンが衝突します。

## セキュリティ上の設計(ローカル運用)

- **サーバーは `127.0.0.1` だけで待ち受けます。** 変更するときは、`server.allowed_hosts` にアクセスする Host 名を追加してください(許可していない Host は 400 で拒否されます)。
- **状態を変える API(`POST` / `DELETE`)は、`X-Requested-With: futurecall` ヘッダーが必須です。** フロントエンド(`frontend/js/api.js`)が付けます。展示機のブラウザで他のサイトを開いても、そのサイトから体験を妨害する要求は送れません。
- **アップロードされた録音は、先頭のバイトで音声形式(wav / webm / ogg / flac / mp3 / aac / mp4 / aiff)を確認してから処理します。** プレイリストなどの音声でないファイルは 415 で拒否し、セッションごと破棄します。デコードは 5 分分で打ち切ります(`audio_prep.MAX_INPUT_SEC`)。
- **キオスク用の Chrome は、`127.0.0.1` / `localhost` 以外へ接続できません**(`--host-resolver-rules`)。マイクの許可を自動で承認する設定のため、他サイトへ移動できないようにしています。
- **起動後はモデルを取りに行きません**(`HF_HUB_OFFLINE=1`)。モデルの取得は `scripts/setup.sh` のときだけです。モデルを更新するときは `HF_HUB_OFFLINE=0 scripts/start.sh` で起動します。
- **依存のバージョンは固定しています。** `requirements-chatterbox.txt`(直接の依存)と `constraints-chatterbox.txt`(推移的な依存を含む全体。`setup.sh` が Apple Silicon で使用)。旧エンジン用の MeloTTS / OpenVoice もコミットを指定しています。
  更新するときは、動作を確認してから `uv pip freeze --python .venv/bin/python > constraints-chatterbox.txt` で作り直します。
