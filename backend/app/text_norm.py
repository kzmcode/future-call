"""読み上げ用テキスト整形・文分割・一人称検出(F-24)。

標準ライブラリのみ。内容はログに出さない。
"""
from __future__ import annotations

import re
import unicodedata

_KANJI_DIGITS = "〇一二三四五六七八九"

# 英単語 -> カタカナ(よく出るものだけ。未登録の英字は削除する)
_EN_WORDS = {
    "ok": "オーケー", "okay": "オーケー", "no": "ノー", "yes": "イエス",
    "line": "ライン", "sns": "エスエヌエス", "ai": "エーアイ", "pc": "ピーシー",
    "tv": "テレビ", "cd": "シーディー", "dvd": "ディーブイディー",
    "youtube": "ユーチューブ", "twitter": "ツイッター", "game": "ゲーム",
    "test": "テスト", "hello": "ハロー", "thank": "サンク", "thanks": "サンクス",
    "sorry": "ソーリー", "mail": "メール", "email": "メール", "web": "ウェブ",
    "app": "アプリ", "smartphone": "スマートフォン", "iphone": "アイフォン",
    "pdf": "ピーディーエフ", "it": "アイティー", "dj": "ディージェイ",
    "bgm": "ビージーエム", "cm": "シーエム", "atm": "エーティーエム",
}
_LETTER_KANA = {
    "a": "エー", "b": "ビー", "c": "シー", "d": "ディー", "e": "イー", "f": "エフ",
    "g": "ジー", "h": "エイチ", "i": "アイ", "j": "ジェー", "k": "ケー", "l": "エル",
    "m": "エム", "n": "エヌ", "o": "オー", "p": "ピー", "q": "キュー", "r": "アール",
    "s": "エス", "t": "ティー", "u": "ユー", "v": "ブイ", "w": "ダブリュー",
    "x": "エックス", "y": "ワイ", "z": "ゼット",
}

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D\U000020E3\U00002190-\U000021FF]"
)
_SENT_END = "。！？!?"


def int_to_kanji(n: int) -> str:
    """整数を漢数字読みに(10->十, 2024->二千二十四, 10000->一万)。"""
    if n < 0:
        return "マイナス" + int_to_kanji(-n)
    if n == 0:
        return "零"
    units = ["", "万", "億", "兆"]
    parts: list[str] = []
    idx = 0
    while n > 0 and idx < len(units):
        n, chunk = divmod(n, 10000)
        if chunk:
            parts.append(_below_10000(chunk, force_one=(idx > 0)) + units[idx])
        idx += 1
    if n > 0:  # 兆を超える巨大数は桁ごとに読む
        return "".join(_KANJI_DIGITS[int(c)] for c in str(n)) + "".join(reversed(parts))
    return "".join(reversed(parts))


def _below_10000(n: int, force_one: bool = False) -> str:
    out = ""
    for val, ch in ((1000, "千"), (100, "百"), (10, "十")):
        d, n = divmod(n, val)
        if d:
            out += ("" if d == 1 else _KANJI_DIGITS[d]) + ch
    if n:
        out += _KANJI_DIGITS[n]
    if force_one and out in ("千", "百", "十"):
        out = "一" + out if out != "十" else "十"
    return out


def _num_repl(m: re.Match) -> str:
    s = m.group(0).replace(",", "")
    if "." in s:
        a, b = s.split(".", 1)
        return int_to_kanji(int(a or 0)) + "点" + "".join(_KANJI_DIGITS[int(c)] for c in b)
    if len(s) > 1 and s.startswith("0") or len(s) > 15:
        return "".join(_KANJI_DIGITS[int(c)] for c in s)  # 007 や長い番号は一桁ずつ
    return int_to_kanji(int(s))


def _en_repl(m: re.Match) -> str:
    w = m.group(0).lower()
    if w in _EN_WORDS:
        return _EN_WORDS[w]
    if len(w) <= 3 and w.isalpha() and w.upper() == m.group(0):  # 略語は一文字ずつ
        return "".join(_LETTER_KANA.get(c, "") for c in w)
    return ""


def normalize_for_tts(text: str, keep_pauses: bool = True) -> str:
    """記号・絵文字・マークダウンを除去し、数字を漢数字に、英字をカナに整える。

    keep_pauses=True(既定): 間の「…」と疑問符「？」を残す(Gemini TTS 用)。
    keep_pauses=False: 「…」を読点に置き換える(MeloTTS/ブラウザ読み上げ用)。
    疑問符は常に全角「？」に統一して残す。
    """
    if not text:
        return ""
    t = str(text).replace("…", "\u0001").replace("‥", "\u0001")  # NFKC で「...」に化けるのを防ぐ
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"\.{3,}|。{3,}", "\u0001", t)
    t = re.sub(r"\u0001+", "\u0001", t)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"https?://\S+", " ", t)
    t = _EMOJI_RE.sub("", t)
    # マークダウン
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+•・]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_`~#>|]+", "", t)
    # 括弧類: 中身は残し、括弧は読点に近い扱いで削除
    t = re.sub(r"[「」『』【】\[\]\(\)（）〈〉《》<>{}]", "", t)
    t = t.replace("\u0001", "…" if keep_pauses else "、")
    t = re.sub(r"[〜~ー]{2,}", "ー", t)
    t = t.replace("~", "").replace("〜", "ー")
    t = t.replace("%", "パーセント").replace("&", "と").replace("+", "たす")
    t = t.replace("=", "イコール").replace("/", "、").replace("\\", "")
    # 数字
    t = re.sub(r"\d[\d,]*(?:\.\d+)?", _num_repl, t)
    # 英字
    t = re.sub(r"[A-Za-z]+", _en_repl, t)
    # 残りの記号(読める文字・句読点以外)を除去
    t = re.sub(r"[^\w\s、。！？!?ー…]", "", t)
    t = t.replace("_", "")
    t = t.replace("!", "！").replace("?", "？")
    # 空白整理(日本語同士の間の空白は削除)
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"(?<=[぀-ヿ一-鿿、。！？]) (?=[぀-ヿ一-鿿、。！？])", "", t)
    t = re.sub(r"\s*\n+\s*", "。", t)
    t = t.strip(" 、")
    t = re.sub(r"、{2,}", "、", t)
    t = re.sub(r"[、。]+(?=[。！？])", "", t)
    t = re.sub(r"、+(?=…)", "", t)
    t = re.sub(r"…{2,}", "……", t)
    t = re.sub(r"。{2,}", "。", t)
    t = re.sub(r"^[、。！？]+", "", t)
    t = t.strip()
    if t and t[-1] not in _SENT_END + "…":
        t += "。"
    return t


def split_parts_for_playback(text: str) -> list[str]:
    """MeloTTS/ブラウザ用: パート本文(「…」保持)を「…」なしに整えて文分割する。"""
    return split_sentences(normalize_for_tts(text, keep_pauses=False))


def _raw_sentences(text: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for ch in text:
        if ch == "\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
            continue
        buf += ch
        if ch in _SENT_END:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s.strip("。！？!?、 ")]


def _split_long(s: str, limit: int) -> list[str]:
    """limit を超える文を読点付近で二分(再帰)。"""
    if len(s) <= limit:
        return [s]
    mid = len(s) // 2
    cands = [i for i, c in enumerate(s) if c == "、" and 8 <= i < len(s) - 8]
    if not cands:
        return [s]
    i = min(cands, key=lambda k: abs(k - mid))
    return _split_long(s[: i + 1], limit) + _split_long(s[i + 1:], limit)


def split_sentences(text: str, min_len: int = 20, max_len: int = 60) -> list[str]:
    """文単位に分割し、短い文は結合して 20〜60 文字程度のチャンクにする。

    先頭チャンクは(極端に短くなければ)1文だけにして TTS を早く開始できるようにする。
    """
    if not text:
        return []
    sents: list[str] = []
    for s in _raw_sentences(text):
        sents.extend(_split_long(s, max_len + 20))
    if not sents:
        return []
    chunks: list[str] = []
    rest = sents
    first = rest[0]
    i = 1
    while len(first) < 6 and i < len(rest):  # 「はい。」のように極端に短い場合のみ結合
        first += rest[i]
        i += 1
    chunks.append(first)
    cur = ""
    for s in rest[i:]:
        if cur and len(cur) + len(s) > max_len:
            chunks.append(cur)
            cur = s
        else:
            cur += s
        if len(cur) >= min_len:
            chunks.append(cur)
            cur = ""
    if cur:
        if chunks and len(cur) < min_len and len(chunks) > 1 and len(chunks[-1]) + len(cur) <= max_len + 20:
            chunks[-1] += cur
        else:
            chunks.append(cur)
    return chunks


_FP_PATTERNS = [
    ("わたし", re.compile(r"(?:わたくし|わたし|私(?![立服鉄物生])|ワタシ)")),
    ("ぼく", re.compile(r"(?:ぼく|僕|ボク)")),
    ("おれ", re.compile(r"(?:おれ|俺|オレ)")),
    ("あたし", re.compile(r"(?:あたし|アタシ)")),
    ("うち", re.compile(r"(?:うち|ウチ)(?=は|が|も|、|って)")),
]


def detect_first_person(transcript: str, default: str = "わたし") -> str:
    """認識テキストから一人称を推定してひらがなで返す。見つからなければ default。"""
    if not transcript:
        return default
    best = default
    best_key = (0, 0)
    for name, pat in _FP_PATTERNS:
        ms = list(pat.finditer(transcript))
        if ms:
            key = (len(ms), -ms[0].start())
            if key > best_key:
                best_key, best = key, name
    return best


# --- 内容語の抽出(エピソード反映チェック/テンプレートの差し込み用。形態素解析は使わない) ---
_RUN_RE = re.compile(r"[一-龥々ァ-ヶー]+")
# 誰の話にも出てくる語(ストーリーに入っていても「反映」とはみなさない)
_STOP_WORDS = ("今日", "昨日", "最近", "自分", "気持", "失敗", "経験", "本当", "全部", "一番", "大事", "電話", "未来", "以前",
               "去年", "先週", "昔", "時", "話", "人", "私", "僕", "俺", "今", "何", "他", "前", "後", "時間", "友達",
               "みんな", "とても", "ちょっと", "ずっと", "すごく", "ミス", "こと", "もの", "ところ")


def content_runs(text: str) -> list[str]:
    """漢字・カタカナの連なり(2 文字以上)。ストップワードそのものは除く。"""
    return [r for r in _RUN_RE.findall(text or "") if len(r) >= 2 and r not in _STOP_WORDS]


def content_bigrams(text: str) -> set[str]:
    """漢字・カタカナ連の文字 bigram の集合(ストップワードを含む bigram は除く)。"""
    out: set[str] = set()
    for run in content_runs(text):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if not any(bg in w for w in _STOP_WORDS if len(w) >= 2):
                out.add(bg)
    return out
