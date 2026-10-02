# 01. セットアップ手順

初回のみ行います。所要時間の目安は 30〜60 分(ダウンロード時間を含む)。空き容量は **20GB 以上** を用意してください。会場ではなく、ネットワークが速い場所で済ませておくと安心です。

## 1. 事前に必要なもの(macOS / Apple Silicon)

| 必要なもの | 確認コマンド | 入れ方 |
|---|---|---|
| Homebrew | `brew --version` | https://brew.sh の手順どおり |
| Python 3.10 | `python3.10 --version` | 下記 |
| git | `git --version` | `brew install git` |
| ffmpeg | `ffmpeg -version` | `brew install ffmpeg` |
| Google Chrome | (アプリ一覧) | https://www.google.com/chrome/ |

MeloTTS と OpenVoice は **Python 3.10** が必要です(3.11 以上は不可)。次のどちらかで入れます。

```bash
# 方法A(推奨): uv
brew install uv
# 方法B: pyenv
brew install pyenv && pyenv install 3.10
```

## 2. かんたんセットアップ(推奨)

ターミナルでこのフォルダに移動し、実行します。

```bash
cd future-call
bash scripts/setup.sh
```

これで「.venv の作成 → ライブラリ導入 → unidic 辞書 → モデル取得 → .env 作成」が自動で行われます。何度実行しても安全です。最後に `=== セットアップ完了 ===` と表示されれば成功です。

Windows の場合はエクスプローラーで `scripts\setup.bat` をダブルクリックします(Python 3.10 または uv が必要)。

## 3. 手動セットアップ(うまくいかないとき)

```bash
cd future-call

# (1) 仮想環境 .venv を作る
uv venv --python 3.10 .venv        # uv の場合
# python3.10 -m venv .venv         # pyenv/brew の場合

# (2) ライブラリを入れる
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-models.txt   # 重い。数分〜十数分

# (2b) OpenVoice は依存が古く MeloTTS と衝突するため、別に --no-deps で入れる
.venv/bin/python -m pip install --no-deps git+https://github.com/myshell-ai/OpenVoice.git@74a1d147b17a8c3092dd5430504bd83ef6c7eb23

# (3) MeloTTS(日本語)用の辞書
.venv/bin/python -m unidic download

# (4) モデル取得と確認
.venv/bin/python scripts/download_models.py

# (5) APIキー用ファイル
cp .env.example .env
```

`requirements-models.txt` には torch と MeloTTS(GitHub 版)が含まれます。librosa は MeloTTS が `librosa==0.9.1` を固定しているため、こちらでは指定せず MeloTTS 経由で入ります(`setuptools<81` は librosa 0.9.1 に必要です)。**OpenVoice は含まれておらず**、`setup.sh` / `setup.bat` が上記 (2b) を別に実行します(手動の場合は忘れずに実行してください)。OpenVoice が使うのは `openvoice.api.ToneColorConverter` のみで、librosa・soundfile・scipy が入っていれば動きます(これらは requirements に含まれます)。`tts.engine: melo` にする場合、OpenVoice 本体とチェックポイントは不要です。

Windows で CPU 版 torch が必要な場合: `.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`

(uv の場合、`pip` が無いと言われたら `uv venv --seed` で作り直すか、`uv pip install -r requirements.txt` を使ってください。)

Windows では `.venv/bin/python` を `.venv\Scripts\python.exe` に、`cp` を `copy` に読み替えます。

### Gemini TTS 用ライブラリ(google-genai)の確認

読み上げに使う Gemini TTS には **google-genai 2.25 以上** が必要です(`requirements.txt` に指定済み)。古いままだと `client.interactions` が無く、エラーも出ずに **こっそり MeloTTS(標準音声)へ切り替わり、表現が平坦になります**。手動で入れた場合や更新したいときは次を実行し、確認します。

```bash
.venv/bin/python -m pip install -U google-genai
.venv/bin/python -c "import importlib.metadata as m; from google import genai; c=genai.Client(api_key='x'); print(m.version('google-genai'), hasattr(c,'interactions'))"
```

`2.25.x` 以上で、末尾が `True` なら OK です。`False` の場合は上の `pip install -U` をもう一度実行してください。

## 4. モデルについて

| モデル | 置き場所 | 取得方法 |
|---|---|---|
| OpenVoice V2 | `models/OpenVoiceV2/` | `download_models.py` が Hugging Face の `myshell-ai/OpenVoiceV2` から取得 |
| MeloTTS 日本語 | 自動キャッシュ | 初回の `TTS(language="JP")` で Hugging Face から取得(**初回はインターネット必須**)。`download_models.py` で事前取得可 |
| faster-whisper | 自動キャッシュ | `download_models.py`、または初回起動時に自動取得(`stt.model_size` のモデル) |

手動で取得する場合は `.venv/bin/huggingface-cli download myshell-ai/OpenVoiceV2 --local-dir models/OpenVoiceV2` でも構いません。次のファイルがあれば十分です。

```
models/OpenVoiceV2/
├── converter/config.json
├── converter/checkpoint.pth
└── base_speakers/ses/jp.pth
```

## 5. 確認方法

```bash
.venv/bin/python scripts/download_models.py
```

期待される出力の末尾:

```
===== 結果 =====
  [OK] OpenVoice V2: 配置済み
  [OK] faster-whisper: small 取得済み
  [OK] MeloTTS(JP): モデル読み込み成功

すべて準備できました。
```

`[NG]` が出た場合は [07_troubleshooting.md](07_troubleshooting.md) を見てください。重いモデルが動かない場合でも、[README のモックモード](../README.md) で画面の確認はできます。

自動テスト(任意):

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## 次のステップ

[02. Gemini APIキーの取得](02_gemini_api.md)
