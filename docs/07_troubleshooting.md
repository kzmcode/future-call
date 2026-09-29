# 07. トラブルシューティング

まず `logs/` の最新ファイルの末尾を見ると手がかりがあります(内容は記録されません)。多くの問題は「サーバーを再起動」で直ります。

## 症状別

### マイクの音が入らない / 音量メーターが動かない

1. Chrome のマイク許可を確認: `chrome://settings/content/microphone` で `localhost` が「許可」か、正しい USB マイクが選ばれているか。
2. macOS「システム設定」→「プライバシーとセキュリティ」→「マイク」で Google Chrome がオンか。
3. 「システム設定」→「サウンド」→「入力」で入力レベルが動くか。動かなければ USB を抜き差し。
4. 変更後は Chrome を再起動([05](05_kiosk_launch.md))。

### 待機画面のまま進まない / 「準備中」が続く(health が ready にならない)

モデルの読み込み中の可能性があります(初回は 1〜2 分)。確認:

```bash
curl http://127.0.0.1:8000/api/health
```

期待値: `{"ready":true,"engines":{"stt":"ok","llm":"ok","tts":"ok"}}`。

- `"unavailable"` のエンジンがある: そのエンジンのモデルが未導入。`.venv/bin/python scripts/download_models.py` で状況確認。動かなくてもフォールバックで体験は可能です。
- 応答がない: サーバーが起動していません。`scripts/start.command` を再実行。

### 生成が遅い(着信までが長い)

目標は 60 秒以内です。次の順で試します(`config.yaml` を編集して再起動)。

1. `stt.model_size: base`
2. `tts.engine: melo`(声クローンなしの標準音声。速い)
3. `experience.record_max_sec: 60`、`llm.target_chars_max: 350`
4. `pipeline.ring_after_chunks: 1`
5. 他のアプリを閉じる。Mac が電源アダプタ接続か確認。

### Gemini のエラー(429 / quota / API key not valid)

- 体験者には見えず、テンプレート物語に切り替わっています。
- `429`・`RESOURCE_EXHAUSTED`: 無料枠の上限。しばらく待つか、上限が回復する時間を待つ([02](02_gemini_api.md))。
- `API key not valid`: `.env` の `GEMINI_API_KEY` を確認(空白・引用符が付いていないか)。
- 通信できない: ネットワーク確認。`llm.engine: template` にすれば API なしで運用できます。

### Gemini TTS(読み上げ)が使えない・429 / 無料枠の上限

- 体験者には見えず、その間は標準音声(MeloTTS + OpenVoice)で読み上げられます。声の表現が平坦になりますが、体験は最後まで進みます。
- 429・`RESOURCE_EXHAUSTED` になったモデルは、`tts.gemini.quota_cooldown_sec`(既定 300 秒)のあいだ飛ばし、`tts.gemini.fallback_models`(既定 `gemini-3.8-flash-lite-tts`)に自動で切り替わります。**全モデルが上限のときだけ** MeloTTS になります。時間が過ぎると自動で再試行します。
- 429 は SDK に再試行させず、その場で次のモデルへ進みます(以前は SDK の自動再試行が最大 25 秒かかって「タイムアウト」になり、lite に切り替わらず MeloTTS になっていました)。1 日あたりの上限(`PerDay`)は 30 分、1 分あたりの上限(`PerMinute`)は 429 の `retryDelay`+2 秒(30〜300 秒)だけ飛ばします。
- **ログに Gemini TTS のモデル切り替え(`using fallback model=...`)や `quota exhausted model=...` が出たら**、主モデルの無料枠が上限です。動作は続きますが、声が少し控えめになる場合があります。頻繁なら体験の間隔をあけるか、<https://aistudio.google.com/rate-limit> で上限を確認し、[02](02_gemini_api.md) の課金設定を検討してください。`unavailable on all models` が出ているなら全モデルが上限(または失敗)で、MeloTTS で読み上げています。
- 同じモデルで連続 3 回失敗すると、そのモデルを 60 秒お休みします。タイムアウトが多いときは `tts.gemini.timeout_sec` を長くするか、`tts.gemini.model: gemini-3.8-flash-lite-tts` を試します。
- 使わないと決めたなら `tts.engine: openvoice`(または `melo`)にします。

### 読み上げの声が不自然・平坦・機械的

- まず Gemini TTS が使われているか確認します。**google-genai が古い(2.25 未満)と、エラーなしで MeloTTS に切り替わります**(次の項目)。
- `GEMINI_API_KEY` が空・間違いのときも、標準音声になります([02](02_gemini_api.md))。
- 上限(429)の冷却中は標準音声です。5 分ほど待つと戻ります。
- 声色変換(OpenVoice)に失敗すると、体験者に似ていない Gemini の声のままになります。`logs/futurecall.log` を確認してください。
- 話し方を変えたいときは `tts.gemini.default_style`、声の種類は `voice_low` / `voice_high` を調整します。

### google-genai が古い(`interactions` が無い)

Gemini TTS は google-genai 2.25 以上が必要で、古いと **エラーが出ずに** 標準音声になります。次で確認・更新します。

```bash
.venv/bin/python -m pip install -U google-genai
.venv/bin/python -c "from google import genai; print(hasattr(genai.Client(api_key='x'), 'interactions'))"
```

`True` になれば OK です。更新後はサーバーを再起動します。

### 問いかけのあとの間が終わらない / 早く進みすぎる

- **いつまでも続きが再生されない**(誰も話していないのに): 環境音・周囲の騒音・スピーカーの回り込みをマイクが「話し声」と判断しています。`experience.reply_wait.speech_threshold` を上げる(0.03 → 0.05)、`audio.ambient_volume` を下げる、スピーカーとマイクを離す。最大でも `max_reply_sec`(15 秒)で進みます。
- **答えている途中で進んでしまう**: `silence_end_sec` を長く(1.2 → 1.8)。
- **答えても反応せず、5 秒たってから進む**: `speech_threshold` を下げる(0.03 → 0.02)。マイクの入力音量も確認。
- **間が全く入らない**: `reply_wait.enabled` が false になっていないか、`llm.reply_pauses` が 0 でないか確認。
- 待たなくてよいなら `experience.reply_wait.enabled: false`。手順は [04](04_audio_devices.md)。

### 環境音が大きい・うるさい

`audio.ambient_volume` を下げます(0.12 → 0.06)。要らなければ `audio.ambient_enabled: false`。声が聞き取りにくい場合や返事の検知が乱れる場合も、まず下げてください。変更後はサーバーを再起動します。

### 音が出ない

1. Mac の出力デバイス(サウンド → 出力)が意図したスピーカーか、ミュートでないか。
2. Chrome のタブがミュートされていないか。`chrome://settings/content/sound` で `localhost` が許可か。
3. `audio.ringtone_volume` / `call_volume` が 0 になっていないか。
4. 最初の操作(「はじめる」の押下)前だと着信音が鳴らないブラウザ設定の場合があります。キオスク起動([05](05_kiosk_launch.md))を使う。

### `pip install -r requirements-models.txt` が ResolutionImpossible(librosa の衝突)で失敗する

`Cannot install ... librosa>=0.10 ... conflicting dependencies` や `no matching distributions available for librosa` と出る場合です。

- 原因: MeloTTS が `librosa==0.9.1` を固定しているため、別の範囲の librosa を指定すると解決できません。
- 対処: 最新の `requirements-models.txt` は librosa を指定しません(MeloTTS 経由で 0.9.1 が入ります)。最新のファイルに更新してから `scripts/setup.sh`(Windows は `scripts\setup.bat`)を再実行してください。何度実行しても安全で、入れ済みのものは再利用されます。
- 手動の場合: `.venv/bin/python -m pip install -r requirements-models.txt` の後に OpenVoice(`--no-deps`)と `python -m unidic download` を実行します([01](01_setup.md))。
- `No module named 'pkg_resources'` と出る場合: `.venv/bin/python -m pip install "setuptools<81"`

### モデルのダウンロードが 404 になる(`jp.pt`)

`scripts/download_models.py` で `HTTP Error 404` / `base_speakers/ses/jp.pt` と出る場合です。

- 原因: OpenVoiceV2 の実際のファイル名は `jp.pth` です(古い版のスクリプトが `jp.pt` を取りに行っていました)。
- 対処: 最新版に更新して `scripts/setup.sh` を再実行するか、`.venv/bin/python scripts/download_models.py` だけを実行します。すでにある `converter/` のファイルは再ダウンロードされず、不足している `jp.pth` だけが取得されます。

### OpenVoice のインストールエラー(Apple Silicon)

- Python が 3.10 か確認: `.venv/bin/python --version`
- OpenVoice は依存が古く衝突するため、`--no-deps` で入れます(`setup.sh` がこの手順を自動で実行します)。
  ```bash
  .venv/bin/python -m pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git
  ```
- `git` や Xcode Command Line Tools が無い場合: `xcode-select --install`
- `av` や `pyopenjtalk` 関連のビルドエラー: `brew install ffmpeg cmake` してから再実行。
- どうしても入らない場合は `tts.engine: melo` にして運用(声クローンなし)。

### unidic / MeCab のエラー(`Can't find dictionary` など)

```bash
.venv/bin/python -m unidic download
```

### MPS(Apple GPU)まわりのエラー・不安定

`config.yaml` で `tts.device: cpu` にします(既定)。`mps` は環境により失敗します。

### MeloTTS の初回に失敗する

MeloTTS は初回に Hugging Face からモデルを取得するので、インターネットが必要です。ネットにつないで `.venv/bin/python scripts/download_models.py` を実行してください。

### ポートが使用中(Address already in use)

前のサーバーが残っています。

```bash
lsof -i :8000          # 使用中のプロセス確認
kill <PID>             # 表示された PID を停止
```

または `config.yaml` の `server.port` を 8001 などに変更します。Windows: `netstat -ano | findstr :8000` → `taskkill /PID <PID> /F`。

### No module named pip と出る

`uv venv` を `--seed` なしで作った `.venv` には pip が入っていないのが原因です。最新の `setup.sh` / `setup.bat` は自動で pip を導入します。直らないときは `rm -rf .venv` してから再実行してください。

### `AssertionError: assert frame.f_back is not None`

原因: `python - <<'PY'` のように標準入力でコードを実行すると、呼び出し元のファイルが無く、引数なしの `load_dotenv()` が `.env` を探せず落ちます。

対処: リポジトリ直下で `load_dotenv(".env")` のように `.env` を明示します(docs の試験コードは対応済み)。あわせて、`.env` の `GEMINI_API_KEY` が空でないか確認してください。

### `OpenVoice load failed` が出て声が変わらない(標準音声のまま)

- `logs/futurecall.log` に `OpenVoice load failed (クラス名: メッセージ)` が出ます。`step=prepare_voice mode=standard` のままなら声クローンは動いていません。
- 過去の原因: インストールされた OpenVoice の `ToneColorConverter` が `enable_watermark` を受け付けず `TypeError` になっていた(透かしの `wavmark` は不要)。現在は自動で回避します。
- 別のメッセージのときは、メッセージ内容に従って `models/OpenVoiceV2/converter/{config.json,checkpoint.pth}` と `base_speakers/ses/jp.pth` の存在、`pip show torch` を確認し、`scripts/setup.sh` を再実行します。

### 声があまり似ない

- マイクを口に近づけ、静かな向きに置く([04](04_audio_devices.md))
- 20 秒以上、はっきり話してもらう。`reference.min_voiced_sec` を満たさないと標準音声になります。
- 仕様上「似た声」程度です(ゼロショット方式の限界)。OpenVoice は声色(音色)だけを写し、話し方・抑揚・間は Gemini の声のままです。
- `reference.denoise: false`(既定)を確認。true だと声色が似にくくなります。
- `phone_fx.low_hz / high_hz` を広げる(例 250 / 3800、さらに 200 / 4000)と似て聞こえます。電話らしさとのトレードオフです。
- `tts.gemini.voices` に体験者の声の高さに近い音声を追加します。声の高さが近いほうが自然です(差は小さい)。
- `tts.tau` は 0.1〜1.0 でほぼ差がありません。既定 0.5 のままで構いません。
- 試して効果がなかったもの: 参照音声を短く(15 秒)/ 16 kHz に落とす / 複数クリップに分割 / Gemini 出力の事前ピッチシフト(いずれも同等か悪化)。

### 画面が固まった

画面の左上を 3 秒長押し(隠しリセット)。それでも戻らなければ Chrome を `Cmd + Q` で終了し、`start.command` を再実行します。

## それでも解決しないとき

`logs/` フォルダと、`curl http://127.0.0.1:8000/api/health` の出力を担当者に渡してください。デモだけ動かしたいときは、[README のモックモード](../README.md) を使います。
