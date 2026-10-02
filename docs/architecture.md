# アーキテクチャと実装契約(Interface Contract)

「未来の自分からの電話」アプリ(`future_call_requirements.md`)の実装における、モジュール分割・インターフェース・設定キーの取り決めです。
各モジュールはこの契約に従って独立に実装されています。変更する場合は必ずこの文書も更新してください。

## 1. ディレクトリ構成と担当

```
future-call/
├── config.yaml                 # 設定ファイル(F-62)                         [core]
├── .env.example                # GEMINI_API_KEY のひな形                       [core]
├── requirements.txt            # 軽量依存(サーバー・Gemini・音声処理)          [core]
├── requirements-models.txt     # 重量依存(faster-whisper, MeloTTS, OpenVoice)  [core]
├── backend/
│   ├── app/
│   │   ├── __init__.py                                                       [core]
│   │   ├── main.py             # FastAPI アプリ、ルーティング、静的配信          [core]
│   │   ├── config.py           # config.yaml + .env 読み込み                   [core]
│   │   ├── session.py          # セッション管理・一時ファイル削除(S-02)        [core]
│   │   ├── pipeline.py         # STT→LLM→TTS→FX のオーケストレーション         [core]
│   │   ├── mocks.py            # モデル無しで動かすためのモック実装              [core]
│   │   ├── logging_setup.py    # ログ設定(S-03: 内容は記録しない)             [core]
│   │   ├── audio_prep.py       # 入力音声の正規化・参照音声の前処理・F0推定      [stt]
│   │   ├── stt.py              # faster-whisper による音声認識                  [stt]
│   │   ├── story.py            # Gemini によるストーリー生成・安全対策          [story]
│   │   ├── story_templates.py  # フォールバック用テンプレート(5種以上+寄り添い型) [story]
│   │   ├── text_norm.py        # 読み上げ用整形・文分割(F-24)                  [story]
│   │   ├── tts.py              # MeloTTS + OpenVoice V2 声クローン             [tts]
│   │   └── phone_fx.py         # 電話音質エフェクト(F-34)                     [tts]
│   └── tests/                  # pytest(各担当が自分のモジュールのテストを置く)
├── frontend/                   # 素の HTML/CSS/JS(ビルド不要)                  [frontend]
│   ├── index.html
│   ├── css/style.css
│   └── js/*.js
├── scripts/
│   ├── start.sh / start.command / start.bat   # ワンクリック起動(F-64)       [core]
│   └── setup.sh / setup.bat / download_models.py                           [docs]
└── docs/                       # チュートリアル・運用マニュアル                  [docs]
```

- Python は **3.10**(MeloTTS / OpenVoice の動作要件)。開発用 venv は `.venv/`。
- バックエンドは `backend/` をカレントにして `uvicorn app.main:app` で起動する想定(`python -m app.main` でも起動可)。
- `config.yaml` / `.env` はリポジトリ直下。`config.py` はリポジトリ直下を基準にパスを解決する。

## 2. 設計原則

- **体験者にエラーを見せない(F-61)**: 各モジュールは失敗時にフォールバックする。例外を投げてよい箇所は下記シグネチャに明記したものだけ。pipeline がそれを捕捉する。
- **内容をログに残さない(S-03)**: `logging.getLogger(__name__)` を使い、認識テキスト・ストーリー本文・ファイル内容は絶対にログに出さない。処理時間・エラー種別(例外クラス名)・文字数などの数値のみ。
- **データはセッションの作業ディレクトリ内にのみ書く(S-02)**: 一時ファイルは必ず pipeline から渡される `work_dir` 配下に作る。セッション削除時にディレクトリごと消す。
- **設定は dict で受け取る**: 各エンジンモジュールは `config.py` に依存せず、自分のセクションの `dict` を受け取る。
- **重いライブラリは遅延 import**: `faster_whisper`, `torch`, `melo`, `openvoice` はメソッド内で import する。未インストールでもモジュール自体は import でき、テストが通ること。

## 3. モジュールインターフェース

### 3.1 audio_prep.py [stt]

```python
@dataclass
class ReferenceInfo:
    path: str | None          # 前処理済み参照音声 WAV(失敗時 None)
    voiced_sec: float         # 有声区間の合計秒数
    median_f0_hz: float | None  # 声の高さの中央値(推定不可なら None)
    ok: bool                  # 声クローンに使える品質か(voiced_sec >= cfg["min_voiced_sec"] など)

def normalize_input(src_path: str, dst_wav_path: str, sample_rate: int = 16000) -> float:
    """任意形式(WAV 推奨、webm/ogg も可能なら)の入力をモノラル 16bit WAV に変換。長さ(秒)を返す。失敗時は例外。"""

def prepare_reference(wav_path: str, out_path: str, cfg: dict) -> ReferenceInfo:
    """ノイズ除去(簡易スペクトルゲート等)・無音カット・声のはっきりした区間の抽出(最大 cfg['max_sec'] 秒)と F0 推定。決して例外を投げない。"""
```

`cfg` は `config.yaml` の `reference` セクション。

### 3.2 stt.py [stt]

```python
class SpeechRecognizer:
    def __init__(self, cfg: dict): ...        # 重い処理はしない
    def load(self) -> None: ...                # モデル読み込み(起動時に一度)。失敗時は例外
    def transcribe(self, wav_path: str) -> str: ...  # 日本語テキスト。失敗時は例外(pipeline が "" 扱い)
```

`cfg` は `stt` セクション。

### 3.3 story.py / text_norm.py / story_templates.py [story]

```python
@dataclass
class StoryResult:
    text: str                 # 表示・デバッグ用の本文(300〜450文字目安)
    sentences: list[str]      # 読み上げ用に整形・分割済みのチャンク(1チャンク = 1〜2文、目安 20〜60 文字)
    first_person: str         # "わたし" / "ぼく" / "おれ" 等
    is_serious: bool          # 深刻な内容(S-20)と判定されたか
    source: str               # "gemini" | "template" | "template_serious"

class StoryGenerator:
    def __init__(self, cfg: dict, api_key: str | None, future_years: int): ...
    def generate(self, transcript: str) -> StoryResult: ...   # 決して例外を投げない
```

- `text_norm.normalize_for_tts(text: str) -> str`、`text_norm.split_sentences(text: str) -> list[str]` を公開する。
- 認識テキストが空・極端に短い(`cfg["min_transcript_chars"]` 未満)場合は Gemini を呼ばずテンプレート(F-12)。
- Gemini は `google-genai` SDK(`from google import genai`)。JSON 出力(本文・一人称・深刻判定・子ども判定)。タイムアウト `cfg["timeout_sec"]`(20秒)、失敗時テンプレート(F-23)。
- 送るのは認識テキストのみ(F-26)。

### 3.4 tts.py / phone_fx.py [tts]

```python
@dataclass
class VoiceContext:
    mode: str                 # "clone" | "standard"
    # 以下は実装依存(target_se, pitch_shift_semitones, melo speaker id など)

class SpeechSynthesizer:
    def __init__(self, cfg: dict): ...        # 重い処理はしない
    def load(self) -> None: ...                # MeloTTS(JP) と OpenVoice V2 変換器の読み込み。失敗時は例外
    def prepare_voice(self, reference_wav: str | None, work_dir: str,
                      median_f0_hz: float | None = None) -> VoiceContext: ...
        # 参照音声から話者埋め込みを抽出。失敗・参照音声なしなら mode="standard"(F-35)。決して例外を投げない
    def synthesize(self, ctx: VoiceContext, text: str, out_wav: str) -> None: ...
        # 1チャンクを合成して out_wav に書く。clone 失敗時は内部で standard にフォールバック。
        # standard でも失敗したときのみ例外

# phone_fx.py
def apply_phone_effect(in_wav: str, out_wav: str, cfg: dict) -> None: ...
    # 300〜3400Hz 帯域制限・軽いノイズ・軽いコンプレッション。出力はモノラル 16bit WAV。
    # 失敗時は例外(pipeline は無加工の音声で続行する)
```

`cfg` は `tts` セクション / `phone_fx` セクション。標準音声フォールバック(F-35)は MeloTTS の JP 話者 + 体験者の F0 に合わせたピッチシフト。
Q-06(未来の声を少し低くする加工)は `tts.age_voice_shift` 設定で ON/OFF でき、既定は OFF。

### 3.5 mocks.py [core]

`MockRecognizer`(固定の失敗エピソード文を返す)と `MockSynthesizer`(文字数に比例した長さのトーン/ノイズ WAV、macOS では `say` コマンドがあれば使ってもよい)を、上記と同じシグネチャで提供する。`stt.engine: mock` / `tts.engine: mock` で切り替え、重いモデル無しで一連の体験を通せるようにする。

### 3.6 pipeline.py [core]

1. アップロードを `work_dir/input.*` に保存 → `normalize_input` で `input.wav`
2. 並列: `prepare_reference` と `transcribe`
3. `StoryGenerator.generate(transcript)`(同時に `prepare_voice` を実行)
4. `StoryResult.sentences` を順に `synthesize` → `apply_phone_effect` → `chunk_{i}.wav` を ready にする(F-33)
5. `ring_after_chunks` 個(`all` なら全チャンク)できた時点で phase=`ready`
6. 合成が全滅した場合、または `total_timeout_sec`(180秒)までに 1チャンクもできない場合は `playback="browser_tts"` とし、文リストを返してブラウザの音声合成で再生する(最終フォールバック)

モデル(STT/TTS)はサーバー起動時にバックグラウンドで `load()` する。ロードに失敗したエンジンは「利用不可」として扱い、フォールバック経路を使う。

## 4. HTTP API [core ↔ frontend]

すべて JSON(音声以外)。ベースパス `/api`。フロントエンドは `/` で静的配信。

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/health` | `{"ready": bool, "engines": {"stt": "ok"\|"loading"\|"unavailable", "llm": ..., "tts": ...}}` |
| GET | `/api/config` | フロント用設定(下記) |
| POST | `/api/sessions` | 新規セッション。既存セッションはすべて削除(展示は1台1人)。`{"session_id": "..."}` |
| POST | `/api/sessions/{id}/recording` | multipart: `audio`(WAV)、`duration_sec`。処理をバックグラウンドで開始し `202 {"accepted": true}` |
| GET | `/api/sessions/{id}/status` | 下記 |
| GET | `/api/sessions/{id}/chunks/{index}` | `audio/wav`。未完成なら 404 |
| DELETE | `/api/sessions/{id}` | セッションの全データ削除(F-52)。`204` |
| POST | `/api/reset` | 全セッション削除(F-60)。`204` |
| POST | `/api/client-log` | `{"event": str, "ms": number}`。event はホワイトリスト(`record_start`, `record_submit`, `ring_start`, `answer`, `call_end`, `missed_call`, `staff_reset`, `client_error`)。内容は記録しない |

`GET /api/config` のレスポンス:

```json
{
  "future_years": 10,
  "caller_name": "10年後の自分",
  "record_min_sec": 20,
  "record_max_sec": 90,
  "ring_timeout_sec": 30,
  "missed_call_display_sec": 4,
  "end_screen_sec": 15,
  "consent_idle_sec": 60,
  "low_volume_threshold": 0.02,
  "ringtone_volume": 0.8,
  "call_volume": 1.0,
  "staff_reset_hold_ms": 3000,
  "status_poll_ms": 1000,
  "max_wait_sec": 200
}
```

`GET /api/sessions/{id}/status` のレスポンス:

```json
{
  "phase": "processing",          // "processing" | "ready"
  "step": "stt",                  // "upload" | "stt" | "story" | "tts" | "done"(演出用。内容は含まない)
  "playback": "audio",            // "audio" | "browser_tts"
  "chunks_ready": 2,
  "chunks_total": 7,              // 未確定なら null
  "all_done": false,
  "sentences": null               // playback == "browser_tts" のときのみ文リスト
}
```

- フロントは `phase == "ready"` で着信開始。通話中もポーリングを続け、`chunks_ready` が増えたら続きを取得して途切れなく再生する。
- セッションが存在しない(リセット済み等)場合は 404。フロントは待機画面に戻る。
- フロントが `max_wait_sec` 待っても ready にならない場合は、フロント内蔵のテンプレート文を `speechSynthesis` で読む(最終の最終フォールバック)。

## 5. config.yaml のキー

```yaml
server:
  host: 127.0.0.1
  port: 8000
  open_browser: false

experience:
  future_years: 10              # C-08
  caller_name: null             # null なら "{future_years}年後の自分"
  record_min_sec: 20            # F-04
  record_max_sec: 90            # F-05
  ring_timeout_sec: 30          # F-45
  missed_call_display_sec: 4
  end_screen_sec: 15            # F-51
  consent_idle_sec: 60
  low_volume_threshold: 0.02    # F-08(RMS 0〜1)
  staff_reset_hold_ms: 3000     # F-60
  status_poll_ms: 1000

audio:                          # N-21
  ringtone_volume: 0.8
  call_volume: 1.0

pipeline:
  total_timeout_sec: 240        # N-01 上限
  ring_after_chunks: all        # F-33(all | 数字)
  work_dir: null                # null ならOSの一時ディレクトリ

reference:                      # audio_prep
  max_sec: 30
  min_voiced_sec: 8
  denoise: true

stt:
  engine: faster_whisper        # faster_whisper | mock
  model_size: small             # tiny | base | small | medium
  compute_type: int8
  beam_size: 1
  language: ja

llm:
  engine: gemini                # gemini | template
  model: gemini-3.5-flash-lite
  fallback_models: [gemini-3.1-flash-lite, gemini-3.8-flash]
  timeout_sec: 20               # F-23
  temperature: 0.9
  min_transcript_chars: 10      # F-12
  target_chars_min: 300
  target_chars_max: 450

tts:
  engine: openvoice             # openvoice | melo | mock(melo = 声クローン無しの標準音声のみ)
  device: cpu                   # cpu | mps | auto
  checkpoint_dir: models/OpenVoiceV2
  speed: 1.0
  standard_voice_pitch_match: true   # F-35: 標準音声を体験者の声の高さに寄せる
  age_voice_shift:              # Q-06
    enabled: false
    semitones: -1.0

phone_fx:
  enabled: true
  low_hz: 300
  high_hz: 3400
  noise_db: -45
  compress: true
  sample_rate: 16000

logging:
  dir: logs
  level: INFO
```

`.env`:

```
GEMINI_API_KEY=...
```

---

# 改訂 v2:自然さの向上(Gemini TTS・電話らしい台本・疑似的なやりとり・環境音)

v1 の契約に対する追加・変更点です。**v2 の記述が v1 と矛盾する場合は v2 を優先**します。

## A. 音声合成:Gemini TTS + OpenVoice V2 [tts]

- 新エンジン `tts.engine: gemini_openvoice`(新しい既定値)。流れは ① Gemini TTS(クラウド)で表現豊かに読み上げ → ② OpenVoice V2 で体験者の声色に変換 → ③ 電話音質エフェクト。
- モデル ID: `gemini-3.8-flash-tts`(既定)/ `gemini-3.8-flash-lite-tts`(高速版)。どちらも無料枠あり。出力は 24kHz・モノラル・16bit PCM。公式ドキュメント: https://ai.google.dev/gemini-api/docs/speech-generation(実装前に必ず読み、記載どおりの API を使うこと)。
- 話し方は `style`(例:「懐かしそうに、少し照れながら、やさしく」)で指示する。
- 声の選択: 体験者の F0 に近いプリセット音声を選ぶ(低い声→`voice_low`、高い声→`voice_high`、境界 `voice_split_f0_hz`)。声色変換の元話者埋め込み(src_se)は `jp.pth` ではなく、その Gemini 音声の出力から `extract_se` で抽出し、音声名ごとにメモリにキャッシュする(固定の合成音声なので個人データではない)。
- フォールバック: Gemini TTS がエラー・タイムアウト(`tts.gemini.timeout_sec`)・無料枠上限 → その部分は MeloTTS で合成(従来の経路)→ それも失敗なら例外。
- Gemini TTS に送るのは**ストーリー本文と話し方の指示のみ**。体験者の音声は送らない(F-26 / S-04 を維持)。
- API キーは `GEMINI_API_KEY`(LLM と共通)。`SpeechSynthesizer.__init__(cfg, api_key=None)` で受け取る。

シグネチャの変更:

```python
class SpeechSynthesizer:
    def __init__(self, cfg: dict, api_key: str | None = None): ...
    def synthesize(self, ctx: VoiceContext, text: str, out_wav: str, style: str | None = None) -> None: ...
    # style は Gemini TTS のときだけ使う。MeloTTS 経路では無視
```

`MockSynthesizer.synthesize` も同じく `style=None` を受け付ける。

## B. 電話らしい台本と「パート」構造 [story]

`StoryResult` にフィールドを追加する(既存フィールドは維持):

```python
@dataclass
class StoryPart:
    text: str                  # 読み上げ用に整形済みのパート本文(間投詞・言いよどみ・「…」の間を含む)
    sentences: list[str]       # 同じパートを MeloTTS / ブラウザ読み上げ用に文分割したもの
    wait_for_reply: bool       # このパートの後で体験者の返事を待つか(最後のパートは常に False)

@dataclass
class StoryResult:
    ...                        # v1 のフィールド(text, sentences, first_person, is_serious, source)
    parts: list[StoryPart]     # 1〜3 パート。sentences は全パートの sentences を連結したものと一致させる
    style: str                 # Gemini TTS への話し方の指示(日本語 1 文)
```

- 台本は「えっとね」「あはは」「うーん」などの間投詞・言いよどみ・間(「…」)を自然に含む話し言葉にする(入れすぎない)。
- 既定の構成は 2 パート:
  - パート1 = 導入 + 共感 + 問いかけ(例:「ねえ、覚えてる?」)。短めにして(目安 60〜120 文字)、着信までの時間を短くする。`wait_for_reply=True`
  - パート2 = 返事を受ける短い相づち(返事があっても無くても自然なもの。例:「うん、うん。そうだよね。」)+ 転機 + 現在 + 結び
- 問いかけの数は `llm.reply_pauses`(0〜2、既定 1)。0 なら 1 パートのみ。
- 深刻な内容(S-20)でも問いかけは可能だが、答えを迫らないやさしいもの(例:「…聞こえてる?」)にする。
- テンプレートもすべてパート構造と style を持つ。
- 文字数の上限は相づち・間投詞を含めて `target_chars_max`(450 → 既定 480 に引き上げ)。

## C. パイプラインとステータス API [core]

- チャンク単位: `tts.chunk_unit: part | sentence`。`gemini_openvoice` のときは既定で `part`(1 パート = Gemini TTS 1 回 = 1 チャンク、リクエスト数を抑える)。それ以外は `sentence`(v1 と同じ)。
- `part` 単位のときは、最初のチャンク(パート1)が完成した時点で `phase = "ready"`(`ring_after_chunks` より優先)。
- `synthesize(ctx, text, out_wav, style=story.style)` を呼ぶ。
- `GET /api/sessions/{id}/status` に **`wait_after: list[int]`** を追加する。返事を待つ位置のインデックス。`playback == "audio"` のときはチャンク番号、`"browser_tts"` のときは `sentences` の番号。そのチャンク(文)の再生が終わったら、フロントは返事を待つ。

## D. フロントエンド [frontend]

- **疑似的なやりとり**: `wait_after` の位置で再生を止め、マイクで体験者の声を検知する(録音も送信もしない。音量(RMS)だけを見る)。
  - 話し始めたら、話し終わり(`reply_silence_end_sec` の無音)まで待ってから続きを再生する
  - 誰も話さなければ `reply_no_speech_sec` 後に続きを再生する
  - 話し続けても `reply_max_sec` で打ち切って続きを再生する
  - 待っている間は通話画面に小さく「…」などの演出を出す(「話してね」とは表示しない)
  - スピーカーの音をマイクが拾わないよう、判定は再生停止から `reply_min_pause_sec` 経過後に開始する
- **環境音**: 通話中、未来の自分の周りの生活音(カフェのざわめき、食器の音など)をかすかに流す。既定はオリジナルの音を Web Audio API で生成する(権利問題を避ける)。電話の帯域(300〜3400Hz)に合わせたフィルタを通す。通話開始時にフェードイン、終話でフェードアウト。`ambient_file` を指定すると `frontend/assets/` の音源を使う。
- 同意画面の説明に「読み上げの声づくりにも Google Gemini を使う(送るのは文章だけで、あなたの声は送らない)」旨を加える。

`GET /api/config` に追加するキー:

```json
{
  "reply_wait_enabled": true,
  "reply_no_speech_sec": 5,
  "reply_silence_end_sec": 1.2,
  "reply_max_sec": 15,
  "reply_min_pause_sec": 0.6,
  "reply_speech_threshold": 0.03,
  "ambient_enabled": true,
  "ambient_volume": 0.12,
  "ambient_file": null
}
```

## E. config.yaml の追加・変更キー

```yaml
experience:
  reply_wait:                   # 疑似的なやりとり
    enabled: true
    no_speech_sec: 5
    silence_end_sec: 1.2
    max_reply_sec: 15
    min_pause_sec: 0.6
    speech_threshold: 0.03      # RMS 0〜1

audio:
  ambient_enabled: true
  ambient_volume: 0.12
  ambient_file: null            # 例: "assets/ambient_cafe.mp3"(frontend/ からの相対パス)

llm:
  reply_pauses: 1               # 問いかけの数 0〜2
  target_chars_max: 480

tts:
  engine: gemini_openvoice      # gemini_openvoice | openvoice | melo | mock
  chunk_unit: auto              # auto | part | sentence(auto = gemini_openvoice なら part)
  gemini:
    model: gemini-3.8-flash-tts
    timeout_sec: 25
    quota_cooldown_sec: 300     # 429 / RESOURCE_EXHAUSTED のあと Gemini TTS を使わない秒数
    voice_low: Charon           # 低めの声の体験者向け(プリセット音声名は公式ドキュメントで確認)
    voice_high: Kore            # 高めの声の体験者向け
    voice_split_f0_hz: 165
    default_style: "懐かしそうに、少し照れながら、やさしく語りかけるように"
```
