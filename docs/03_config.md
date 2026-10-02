# 03. 設定ファイル(config.yaml)の解説

リポジトリ直下の `config.yaml` をテキストエディタで編集し、**サーバーを再起動** すると反映されます。書式は「キー: 値」で、字下げ(スペース2個)が意味を持つので崩さないでください。`#` 以降はコメントです。APIキーは `config.yaml` ではなく `.env` に書きます。

別の設定ファイルを使いたい場合は、環境変数 `FUTURECALL_CONFIG` にそのファイルのパスを指定して起動します(例: `FUTURECALL_CONFIG=/path/to/my.yaml bash scripts/start.sh`)。未指定なら `config.yaml` を読みます。ただし `start.sh` / `start.bat` はホスト名とポートだけは常にリポジトリ直下の `config.yaml` から読むので、`server` の値は `config.yaml` 側で変更してください。

## server

| キー | 既定 | 説明 |
|---|---|---|
| host | 127.0.0.1 | このPC内からのみ接続可。通常は変えない(変えるとネットワーク上の他人が触れる) |
| port | 8000 | 使用ポート。使用中エラーのときは 8001 などに変更 |
| open_browser | false | true でサーバー起動時にブラウザを自動で開く |
| allowed_hosts | [127.0.0.1, localhost, "[::1]"] | 受け付ける Host ヘッダー(DNS rebinding 対策)。上の host も自動で許可。別名(PC名など)でアクセスするときだけ追加 |

## experience(体験の流れ)

| キー | 既定 | 説明 / 変更の目安 |
|---|---|---|
| future_years | 10 | 何年後の自分か。整数。例: 5, 20 |
| caller_name | null | 着信画面の名前。null なら「{年数}年後の自分」。例: `未来のわたし` |
| record_min_sec | 20 | 録音の下限秒数。短いと声の再現が悪くなるので 15 未満は非推奨 |
| record_max_sec | 90 | 上限秒数。到達で自動送信。待ち時間短縮なら 60 |
| ring_timeout_sec | 30 | 着信に応答しない場合、不在着信になるまでの秒数 |
| missed_call_display_sec | 4 | 「不在着信」表示の秒数 |
| end_screen_sec | 15 | 終話画面から待機に戻るまでの秒数 |
| consent_idle_sec | 60 | 同意画面で操作が無いとき待機に戻る秒数 |
| low_volume_threshold | 0.02 | 音量不足の判定(0〜1)。声が小さいと警告されすぎるなら 0.01、鳴らないなら 0.03 |
| staff_reset_hold_ms | 3000 | 隠しリセットの長押し時間(ミリ秒)。誤操作が多ければ 4000 |
| status_poll_ms | 1000 | 状況確認の間隔。通常は変えない |

### experience.reply_wait(疑似的なやりとり)

物語の途中の問いかけ(「ねえ、覚えてる?」)のあと、体験者が声で答えるのを少し待つ機能です。**マイクの音量だけを見ており、録音も送信もしません**。

| キー | 既定 | 説明 / 調整の目安 |
|---|---|---|
| enabled | true | false にすると待たずに続けて再生 |
| no_speech_sec | 5 | 誰も話さないとき、この秒数で続きを再生。長いと間延び、短いと答える前に進む |
| silence_end_sec | 1.2 | 話し終わりと判定する無音の秒数。答える途中で進んでしまうなら 1.5〜2.0 |
| max_reply_sec | 15 | 話し続けても、この秒数で打ち切って続きを再生 |
| min_pause_sec | 0.6 | 再生が止まってから判定を始めるまでの秒数(スピーカー音の回り込み防止) |
| speech_threshold | 0.03 | 「話している」と判定する音量(RMS 0〜1)。**会場で調整**(下記) |

- 声に反応せず、いつも `no_speech_sec` で進む: `speech_threshold` を下げる(例 0.02)。
- 話していないのに反応する / 待ちが終わらない(周囲の騒音・環境音・スピーカーの回り込み): `speech_threshold` を上げる(例 0.05)か、`audio.ambient_volume` を下げる。
- 詳しくは [04_audio_devices.md](04_audio_devices.md) の「返事の検知と環境音の調整」。

## audio(音量)

| キー | 既定 | 説明 |
|---|---|---|
| ringtone_volume | 0.8 | 着信音の音量(0〜1) |
| call_volume | 1.0 | 通話音声の音量(0〜1)。通話は周囲に聞こえないよう会場に合わせ下げる |
| ambient_enabled | true | 通話中に生活音(カフェのざわめきなど)をかすかに流す。false で無し |
| ambient_volume | 0.12 | 環境音の音量(0〜1)。声が聞き取りにくい・返事の検知に影響するなら 0.06 などに下げる |
| ambient_file | null | 自前の音源を使う場合、`frontend/` からの相対パス(例 `assets/ambient_cafe.mp3`)。null ならブラウザが自動生成(権利の心配なし) |

環境音は電話の音域に合わせて加工され、通話開始でフェードイン、終話でフェードアウトします。

調整方法は [04_audio_devices.md](04_audio_devices.md)。

## pipeline

| キー | 既定 | 説明 |
|---|---|---|
| total_timeout_sec | 180 | 生成の上限。超えるとブラウザ内蔵の音声読み上げで代替 |
| ring_after_chunks | 2 | 何文できたら着信を始めるか。待ち時間を減らすなら 1、通話中の途切れが出るなら 3 |
| work_dir | null | 一時ファイルの場所。null で OS の一時フォルダ(通常は変えない) |

## reference(参照音声の前処理)

| キー | 既定 | 説明 |
|---|---|---|
| max_sec | 30 | 声クローンに使う最大秒数。長いと処理が重くなる |
| min_voiced_sec | 8 | 有声区間がこれ未満だと声クローンを諦めて標準音声にする |
| denoise | false | ノイズ除去。**false が既定**(true だと声色が似にくくなる。実測で類似度 約 -0.04)。会場が騒がしくて雑音が声に混ざるときだけ true |

## stt(音声認識)

| キー | 既定 | 説明 |
|---|---|---|
| engine | faster_whisper | `faster_whisper` または `mock`(開発用) |
| model_size | small | `tiny` < `base` < `small` < `medium`。大きいほど正確だが遅い |
| compute_type | int8 | CPU向け。通常は変えない |
| beam_size | 1 | 大きいほど正確だが遅い。1〜5 |
| language | ja | 日本語固定 |

速度と精度の目安(CPU): `tiny` は速いが誤認識が多い、`base` は速く実用的、**`small` が標準**、`medium` は精度が高いが遅くて展示向きでない。生成が遅いときはまず `base` にします。モデル変更後は `scripts/download_models.py` を再実行すると事前取得できます。

## llm(物語生成)

| キー | 既定 | 説明 |
|---|---|---|
| engine | gemini | `gemini` または `template`(常にテンプレート) |
| model | gemini-3.5-flash-lite | Gemini のモデル名([02](02_gemini_api.md)) |
| fallback_models | [gemini-3.1-flash-lite, gemini-3.8-flash] | 主モデルが 404 / NOT_FOUND(提供終了・新規ユーザー不可)または 429 / RESOURCE_EXHAUSTED(無料枠の上限。上限はモデルごと)のとき順に試すモデル。404 で動いたモデルはプロセス内で記憶します。503(一時的な過負荷)のときはその通話だけ次のモデルを使います。全モデルが上限ならテンプレートになります。全体で timeout_sec の範囲内 |
| quota_cooldown_sec | 120 | 429 になったモデルをこの秒数スキップし(次の来場者は即座に次のモデルへ)、過ぎたら再び試します。「1日あたり」の上限のときは自動で 30 分以上にします |
| timeout_sec | 35 | これを超えるとテンプレートに切替 |
| temperature | 0.9 | 高いほど多様。落ち着いた内容にしたいなら 0.7 |
| min_transcript_chars | 10 | 認識結果がこれ未満なら Gemini を使わずテンプレート |
| target_chars_min / max | 300 / 480 | 物語の文字数(相づち・間投詞を含む上限。読み上げ約60〜90秒)。通話を短くするなら 250 / 350 |
| reply_pauses | 1 | 問いかけの数(0〜2)。1 なら物語が 2 パートに分かれ、間に返事待ちが入る。0 なら 1 パートのみで返事待ちなし |

台本には「えっとね」「あはは」などの間投詞や「…」の間が自然に入ります。

## tts(音声合成・声の再現)

| キー | 既定 | 説明 |
|---|---|---|
| engine | gemini_chatterbox | `gemini_chatterbox`(既定): Gemini TTS で表現豊かに読み上げ → Chatterbox VC で体験者の声色だけに変換(話し方・抑揚・間は Gemini のまま)。`gemini_openvoice`: 変換器が OpenVoice。`chatterbox`: MeloTTS + Chatterbox(Gemini の読み上げを使わない)。`openvoice`: MeloTTS + OpenVoice(Gemini の読み上げを使わない)。`melo`: 標準音声のみで**速い**(声クローン無し)。`mock`: 開発用 |
| chunk_unit | auto | 生成・再生の単位。`auto`(`gemini_*` なら `part`、他は `sentence`)/ `part`(パートごと。Gemini への回数が少ない)/ `sentence`(文ごと) |
| device | cpu | `cpu` が最も安定。`mps`(Apple GPU)は速い場合があるが不安定なことがある。`auto` は自動選択 |
| checkpoint_dir | models/OpenVoiceV2 | OpenVoice のモデル置き場(相対パスはリポジトリ直下基準) |
| tau | 0.5 | (OpenVoice のみ。Chatterbox では無視)変換の tau。実測では 0.1〜1.0 で類似度はほぼ同じ(差 0.01 未満)。大きいほど変換のゆらぎが増える |
| speed | 1.0 | 読み上げ速度。0.9 でゆっくり、1.1 で速く |
| standard_voice_pitch_match | true | 声クローン失敗時の標準音声を、体験者の声の高さに寄せる |

### tts.gemini(Gemini TTS。`gemini_chatterbox` / `gemini_openvoice` のとき有効)

読み上げの文章と話し方の指示だけを送ります。体験者の声は送りません。詳細は [02_gemini_api.md](02_gemini_api.md)。

| キー | 既定 | 説明 |
|---|---|---|
| default_style | (電話口の自然な話し方) | 台本側に話し方の指示が無いときの既定 |
| style_suffix | (自然な日本語の指示) | 台本ごとの話し方の指示の後ろに必ず付け足す文。外国人っぽさを抑える。空にすると付けない |
| model | gemini-3.8-flash-tts | 主モデル。高速版は `gemini-3.8-flash-lite-tts`(着信までが遅いときは、これを `model` にして先頭で使う) |
| fallback_models | [gemini-3.8-flash-lite-tts] | 主モデルが 429(無料枠の上限。上限はモデルごと)または 404 のとき、順に試すモデル。少し表現が控えめになる場合あり。全モデルが使えないときだけ MeloTTS。空 `[]` で無効 |
| timeout_sec | 40 | 1 パートの合計の待ち時間(モデルの数で増えない)。超えるとそのパートは MeloTTS で作る |
| quota_cooldown_sec | 300 | 429 になったモデルをこの秒数スキップして再試行する(1 日あたりの上限なら 30 分) |
| voices | Charon 100 / Puck 120 / Kore 160 | `[{name, f0_hz}]` の表。体験者の声の高さ(F0)に最も近い `f0_hz` の音声を選ぶ(声の高さ不明なら 200 Hz 扱い)。`f0_hz` は各音声を実際に合成して測った値。増やすときは、その音声で合成して声の高さを測って追記する |
| voice_low / voice_high / voice_split_f0_hz | Charon / Kore / 165 | `voices` を書かないときの従来の 2 分割(F0 が `voice_split_f0_hz` 未満なら low) |
| default_style | 懐かしそうに、少し照れながら、やさしく語りかけるように | 話し方の指示。物語ごとの指示が無いときに使う |

音声名は Google の公式ドキュメント(https://ai.google.dev/gemini-api/docs/speech-generation)の一覧から選べます。google-genai 2.25 以上が必要です。

任意の上級キー(通常は書かなくてよい):

| キー | 既定 | 説明 |
|---|---|---|
| enable_watermark | false | OpenVoice の透かし機能 |
| torch_threads | min(4, CPU数) | 処理に使うスレッド数。他の処理と競合するとき調整 |
| standard_base_f0_hz | 220 | 標準音声の基準の声の高さ(Hz) |

### age_voice_shift(未来の声を少し低くする加工。Q-06)

| キー | 既定 | 説明 |
|---|---|---|
| enabled | false | true で「年を重ねた声」に少し寄せる。効果は小さいのでリハで聞き比べて決める |
| semitones | -1.0 | 下げる半音数。-1〜-2 程度。下げすぎると不自然 |
| skip_if_child | true | 子どもと推定された場合は加工しない(10年後も若いため) |

## phone_fx(電話音質)

| キー | 既定 | 説明 |
|---|---|---|
| enabled | true | 電話風の加工。合成の粗さも目立たなくなるので基本 true |
| low_hz / high_hz | 250 / 3800 | 通す音域。狭いほど電話らしいが声色が似にくくなる(実測: 300〜3400 → 250〜3800 → 200〜4000 の順に類似度が上がる)。電話らしさを強めたいなら 300 / 3400 |
| noise_db | -45 | 軽い雑音の大きさ。0 に近いほど大きい。雑音が気になるなら -55 |
| compress | true | 音量のばらつきを抑える |
| sample_rate | 16000 | 通常は変えない |

## logging

| キー | 既定 | 説明 |
|---|---|---|
| dir | logs | ログの保存先(リポジトリ直下からの相対)。`futurecall.log`(1MBごとに5世代ローテーション)が作られます。起動スクリプトの標準出力は `logs/server.out` |
| level | INFO | 詳しく見たいとき DEBUG(それでも話の内容は記録されません) |

## 設定例

- **とにかく速くしたい**: `stt.model_size: base`、`tts.engine: melo`、`experience.record_max_sec: 60`、`experience.reply_wait.enabled: false`
- **Gemini の読み上げを速く**: `tts.gemini.model: gemini-3.8-flash-lite-tts`
- **静かな会場で品質重視**: `stt.model_size: small`、`tts.engine: gemini_openvoice`、`reference.denoise: true`
- **API を使わず確認**: `llm.engine: template`
