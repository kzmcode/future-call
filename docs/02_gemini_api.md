# 02. Gemini API キーの取得と設定

未来の物語は Google の Gemini API(無料枠)で作ります。キーが無くても、用意済みのテンプレート物語で体験は完了できますが、体験者の話に沿った物語にはなりません。

## 1. キーを取得する

1. Chrome で https://aistudio.google.com/ を開き、Google アカウントでログインします。
2. 画面の「Get API key」(APIキーを取得)を選びます。
3. 「Create API key」(APIキーを作成)を選び、プロジェクトを選ぶか新規作成します。
4. 表示された `AIza...` で始まる文字列をコピーします。

**キーは他人に見せない・GitHub などに公開しない** でください。

## 2. `.env` に書く

```bash
cd future-call
cp .env.example .env        # setup.sh 実行済みなら作成済み
open -e .env                # テキストエディットで開く
```

次のように書いて保存します(`=` の前後にスペースや引用符は付けません)。

```
GEMINI_API_KEY=ここにコピーしたキー
```

## 3. キーが使えるか試す

**リポジトリ直下**(`.env` があるフォルダ)で実行します。

```bash
.venv/bin/python - <<'PY'
from dotenv import load_dotenv; import os, sys
load_dotenv(".env")   # リポジトリ直下で実行する前提(引数なしの load_dotenv() は標準入力実行だとエラーになる)
key = os.environ.get("GEMINI_API_KEY", "").strip()
if not key:
    sys.exit(".env に GEMINI_API_KEY が設定されていません")
from google import genai
c = genai.Client(api_key=key)
r = c.models.generate_content(model="gemini-3.5-flash-lite", contents="こんにちは、と一言だけ返してください")
print(r.text)
PY
```

挨拶が表示されれば成功です。`API key not valid` はキーの貼り間違い、`429` / `RESOURCE_EXHAUSTED` は無料枠の上限です。

## 4. モデルを変更する

`config.yaml` の `llm.model` を変えます(既定は `gemini-3.5-flash-lite`)。速度重視の Flash 系を推奨します。`gemini-2.5-flash` は以前に使ったことのないユーザーには提供されず(404 NOT_FOUND)、物語がテンプレートになってしまうため、新しいキーでは 3.x 系を使います。主モデルが 404(提供終了)または 429(無料枠の上限)のときは `llm.fallback_models`(既定は `gemini-3.1-flash-lite`、`gemini-3.8-flash` の順。安く速いものを先に、無料枠の少ない 3.8-flash を最後に試します)に自動で切り替わります。無料枠の上限は**モデルごと**で、`gemini-3.8-flash` は 1 日 20 リクエスト程度(確認時点)しかないため、既定では lite 系を主モデルにしています。429 のモデルは `llm.quota_cooldown_sec` のあいだ飛ばし、あとで再試行します。安定運用には課金の有効化を検討してください(次の「無料枠の上限の確認方法」を参照)。思考(thinking)は 3.x 系では無効化できないため(lite 系は minimal、3.8-flash は low)、アプリが `thinking_level` を最小にして遅延を抑えます。モデル名は変更・終了されることがあるため、エラーが出たら AI Studio で最新の名前を確認してください。

```yaml
llm:
  model: gemini-3.5-flash-lite
```

## 5. 無料枠の制限に関する注意

- 1分あたり・1日あたりの回数などの上限があります。**値は変更されるので、展示前に公式ページ(https://ai.google.dev/gemini-api/docs/rate-limits)で最新を確認してください。** 1時間10人程度なら収まる見込みですが、リハーサルで確認すると安心です。
- 上限に達すると Gemini は使えなくなり、物語は自動でテンプレート物語に、読み上げは標準音声に切り替わります。

### 無料枠の上限の確認方法

- 上限は**プロジェクトごと・モデルごと**で、利用ティアによっても異なります。公式ドキュメントには具体的な数値は載っていません。
- 自分のプロジェクトの RPM(1分あたりのリクエスト数)/ TPM(1分あたりのトークン数)/ RPD(1日あたりのリクエスト数)は https://aistudio.google.com/rate-limit で確認できます。
- 1 日の上限は太平洋時間の 0 時にリセットされます(日本時間の 16:00 または 17:00。夏時間かどうかで変わります)。
- 確認時点の実測では、`gemini-3.8-flash` の無料枠は 1 日 20 リクエストでした。
- 読み上げ(`gemini-3.8-flash-tts`)は物語生成とは**別のクォータ**です。同じ画面で確認してください。来場者が増えたときは、物語生成よりこちらが先に上限に達する可能性が高いです。

#### 課金を有効にする場合

- 請求先アカウントをプロジェクトにひも付けると Tier 1 になり、すぐに反映されます。
- 課金を有効にすると、入力内容は Google の製品改善には使われなくなります(無料枠では使われます。詳しくは 6 章)。
- 有料の料金(料金ページ記載。展示前に https://ai.google.dev/gemini-api/docs/pricing で必ず最新を確認してください):
  - `gemini-3.5-flash-lite`: 入力 $0.30 / 100万トークン、出力 $2.50 / 100万トークン
  - `gemini-3.1-flash-lite`: 入力 $0.25 / 100万トークン、出力 $1.50 / 100万トークン
  - `gemini-3.8-flash`: 入力 $0.75 / 100万トークン(2026-12-31 まで)
- 概算(見積もり)として、物語 1 本を入力 約 1.5k・出力 約 0.8k トークンとすると、`gemini-3.5-flash-lite` で来場者 1 人あたり約 $0.002〜0.003(約 0.4 円)です。実際の値はプロンプトや出力の長さで変わります。

## 6. データの取り扱い(重要)

無料枠では、送った入力が **Google のサービス改善に使われる場合があります**。そのため同意画面で「話した内容を文字にしたテキストが外部の AI サービス(Google Gemini)に送られる」ことを告知しています。送られるのは **文字起こしのテキストのみ** で、録音音声は送られません。体験者にも案内してください。より厳密に扱いたい場合は、有料プランなど条件の異なるプランを検討してください(条件は Google の規約で確認)。

## 7. Gemini TTS(読み上げ音声)

v2 では、未来の自分の **読み上げの声そのものも Gemini TTS で作ります**(`tts.engine: gemini_openvoice`)。流れは「Gemini TTS で感情豊かに読み上げ → OpenVoice で体験者の声色に寄せる → 電話音質にする」です。

- **同じ API キー** (`GEMINI_API_KEY`) を物語生成と読み上げで共用します。追加の設定は要りません。
- ライブラリは **google-genai 2.25 以上** が必要です([01_setup.md](01_setup.md))。古いと自動で MeloTTS に切り替わります。
- モデル(`config.yaml` の `tts.gemini.model`):
  - `gemini-3.8-flash-tts`(既定): 表現が豊か
  - `gemini-3.8-flash-lite-tts`: **より速い**。着信までが遅いときに切り替える
  - どちらも無料枠があります(上限は公式の料金・制限ページで確認)。
- **モデルの切り替え(フォールバック)**: 無料枠の上限は「プロジェクト × モデル」ごとです。主モデルが上限(429)になると、`tts.gemini.fallback_models`(既定 `gemini-3.8-flash-lite-tts`)へ自動で切り替わります。lite は主モデルより表現が少し控えめに聞こえることがあります。**すべてのモデルが使えないときだけ** MeloTTS になります。現在の上限と使用状況は <https://aistudio.google.com/rate-limit> で確認できます。
- 声は体験者の声の高さで自動で選ばれます(低め → `voice_low` = Charon、高め → `voice_high` = Kore。境界は `voice_split_f0_hz`)。
- **送るのは物語の文章と話し方の指示だけ**です。体験者の声は Gemini には送られません。
- **データの取り扱い**: 無料枠では、送った入力が Google の製品改善に使われる場合があります(料金ページに記載)。同意画面にも「読み上げの声づくりにも Gemini を使う(送るのは文章だけ)」と書いてあります。

### 上限・失敗したとき

- 429 / `RESOURCE_EXHAUSTED`(無料枠の上限)になったモデルは、`tts.gemini.quota_cooldown_sec`(既定 300 秒。1 日あたりの上限と分かれば 30 分)のあいだ飛ばし(待たずに次のモデルへ)、時間が過ぎると自動で再試行します。全モデルが上限のあいだは Gemini を呼ばず、標準音声(MeloTTS + OpenVoice)で読み上げます。
- 404(そのモデルが使えない)はプロセスが動いている間そのモデルを飛ばします。503(過負荷)はその 1 回だけ次のモデルへ進みます。
- タイムアウト(`tts.gemini.timeout_sec` 25 秒。モデルの数では増えません)・空の音声など、その他のエラーのときは、その部分だけ MeloTTS に切り替わります。同じモデルで連続 3 回失敗すると、そのモデルを 60 秒お休みします。
- 声色変換に使う元の声の特徴は「モデル × 声」ごとに 1 回だけ抽出するので、切り替え後の最初のパートだけ少し時間がかかることがあります(追加の API 呼び出しはありません)。
- API キーが無いときは `tts.engine: openvoice` と同じ動きになります。
- OpenVoice の声色変換に失敗したときは、変換前の Gemini の声のまま再生します。

### 設定の切り替え

```yaml
tts:
  engine: gemini_openvoice        # Gemini を使わないなら openvoice(声クローンのみ)または melo(標準音声のみ)
  gemini:
    model: gemini-3.8-flash-tts                        # 主モデル
    fallback_models: [gemini-3.8-flash-lite-tts]       # 主モデルが上限のとき順に試す
```

### 動作テスト

リポジトリ直下で実行します。

```bash
.venv/bin/python - <<'PY'
from dotenv import load_dotenv; import os, sys
load_dotenv(".env")   # リポジトリ直下で実行する前提(引数なしの load_dotenv() は標準入力実行だとエラーになる)
key = os.environ.get("GEMINI_API_KEY", "").strip()
if not key:
    sys.exit(".env に GEMINI_API_KEY が設定されていません")
from google import genai
c = genai.Client(api_key=key)
print("interactions:", hasattr(c, "interactions"))   # False なら google-genai が古い
PY
```

`True` ならライブラリは対応しています。実際の音は体験を 1 回通して確認し、`logs/futurecall.log` に Gemini TTS のエラーが出ていないかを見てください。

## 8. 失敗したときの動き

通信エラー・タイムアウト(20秒)・上限到達・キー未設定のときは、体験者には何も見せず **テンプレート物語** に切り替わります(体験は最後まで進みます)。ネット切断時も同様です。API を使わず常にテンプレートにしたい場合は `llm.engine: template` にします。
