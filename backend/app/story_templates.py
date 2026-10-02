"""フォールバック用テンプレートストーリー(F-12 / F-23 / S-20 / 改訂 v2 §B)。

どんなエピソードにも当てはまる汎用の内容。5部構成
(導入・共感・転機・現在・結び)を「パート」構造で持つ:
  パート1 = head(導入+共感)+ question(問いかけ)
  パート2 = ack(相づち)+ tail(転機+現在+結び)
reply_pauses=0 のときは head + tail の 1 パートにする(問いかけと相づちは省く)。
reply_pauses=2 のテンプレートは 1 問に丸める。300〜480文字、平易な言葉、間投詞と「…」を含む。
プレースホルダ: {N}=未来の年数, {me}=一人称, {you}=呼びかけ(君/あなた)。
"""
from __future__ import annotations

import random
import re
from typing import NamedTuple

from .text_norm import content_runs


class Template(NamedTuple):
    style: str
    head: str
    question: str
    ack: str
    tail: str

    def full_text(self) -> str:
        return self.head + self.question + self.ack + self.tail

    def merged_text(self) -> str:
        return self.head + self.tail


_OPEN = "もしもし、びっくりしたよね。{N}年後の{me}だよ。"
_S_WARM = "懐かしそうに、少し照れながら、やさしく語りかけるように"
_S_SERIOUS = "静かに、落ち着いて、そっと寄り添うようにやさしく"

GENERIC: list[Template] = [
    Template(_S_WARM,
        _OPEN + "えっとね、{you}が話してくれたあのときのこと、こっちの{me}もちゃんと覚えているよ。"
        "うまくいかなくて、くやしくて、心がぎゅっとなったよね。",
        "ねえ、あの日のこと、覚えてる？",
        "うん、うん。そうだよね。",
        "その気持ちを、ひとりでかかえなくていいんだよ。"
        "でもね、あの日のことがあったから、{me}は少しずつ考え方を変えられたんだ。"
        "人の話をよく聞くようになったし、こまったときは「助けて」と言えるようになった。"
        "そうしたら、思いがけない出会いがあって、毎日が少しだけ楽しくなったんだ。"
        "今の{me}は、大きな成功をしたわけじゃないよ。あはは。"
        "でも、毎日ふつうにごはんを食べて、笑って、ちゃんと前に進んでいる。"
        "あのときの経験が、今の{me}をそっと支えてくれているんだ。"
        "だから、{you}も大丈夫。ゆっくりでいいから、自分のペースで歩いてね。応援しているよ。じゃあ、またね。"),
    Template(_S_WARM,
        _OPEN + "さっき話してくれたこと、聞こえたよ。あのとき、本当にがんばったのに、思うようにいかなかったよね。"
        "はずかしくて、逃げ出したい気持ちになったこと、{me}はよく覚えている。",
        "……ねえ、あのとき、どんな気持ちだった？",
        "…そっか。うん、わかるよ。",
        "でも、あのとき悔しかったから、{me}はもう一度やってみようと思えたんだ。"
        "最初は小さなことからだった。昨日より少しだけ、ていねいにやってみる。それだけ。"
        "そのうちに、まわりの人が「いいね」と言ってくれるようになって、少しずつ自信がついたんだよ。"
        "{N}年たった今、{me}は自分の好きなことを、ゆっくり楽しみながら続けている。"
        "うーん、あのころの失敗があったから、今のやさしい{me}がいるんだと思う。"
        "だから安心して。{you}の歩いてきた道は、ちゃんとつながっているよ。じゃあ、またね。"),
    Template(_S_WARM,
        _OPEN + "今、{you}の心の中には、あのときの出来事がまだ残っているよね。"
        "思い出すたびに、胸がちくっとするのも、{me}はわかるよ。すごく大事なことだったからだよね。",
        "ねえ、今もときどき、思い出したりする？",
        "うんうん。そうだよね。",
        "うーん、実はね、あのことがあってから、{me}のまわりに、ふしぎといろいろなことが起きたんだ。"
        "同じように悩んでいる人と話せるようになったり、思ってもいなかった場所に行けたり。"
        "遠まわりに見えた道が、あとから見ると、ちゃんと必要な道だったんだよ。"
        "今の{me}は、いそがしいけれど、けっこう幸せにくらしている。"
        "うまくいかない日もあるけれど、「まあ、なんとかなるよ」と思えるようになった。"
        "それは、あのときの{me}ががんばってくれたおかげだよ。ありがとう。"
        "{you}のこと、ずっと応援しているからね。じゃあ、またね。"),
    Template(_S_WARM,
        _OPEN + "ちょっとだけ、{you}に伝えたくて電話したんだ。"
        "あのときの話、ちゃんと聞いたよ。うまくいかなかったことを、ずっと気にしていたよね。",
        "ねえ、あのときのこと、覚えてる？",
        "うん、うん。そっか。",
        "あのとき、{me}は自分をたくさんせめてしまった。でもね、今思うと、あれは本気だったからこそのくやしさなんだ。"
        "それからしばらくして、ある人にかけてもらった一言で、気持ちがふっと軽くなったんだ。"
        "そこから、少しずつ人に相談できるようになって、ひとりでがんばりすぎることも減った。"
        "{N}年後の今は、無理をしすぎず、自分らしいやり方で毎日を過ごしているよ。"
        "あのときの経験は、今もお守りみたいに、{me}の中にあるんだ。"
        "だから{you}も、今の気持ちを大事にしてね。きっと、大丈夫。じゃあ、またね。"),
    Template(_S_WARM,
        _OPEN + "夢みたいだけど、本当に未来から電話しているんだよ。"
        "さっきの話を聞いて、あのときの気持ちがぜんぶよみがえってきた。悲しくて、くやしくて、どうしていいかわからなかったよね。",
        "ねえ、あのとき、だれかに話せた？",
        "…そっか。うん、うん。",
        "でも、そんな{you}に、ひとつだけいい知らせがあるんだ。"
        "あのあと、{me}はゆっくり立ち直って、少しずつ新しいことにちょうせんしたの。"
        "続けているうちに、いっしょに笑える仲間もできて、思っていたよりずっと楽しい毎日になったんだよ。"
        "もちろん、今でも失敗することはあるよ。だけど、こわがらずにやってみようと思える。"
        "その強さは、あのときの経験がくれたものなんだ。"
        "だから、{you}はそのままで大丈夫。いつかこの電話のことを思い出してね。じゃあ、またね。"),
    Template(_S_WARM,
        _OPEN + "今日はね、あのときがんばっていた{you}に、ありがとうを言いたくて電話したんだ。"
        "えっと、思いどおりにならなくて、なみだが出そうになったこと、{me}も覚えているよ。",
        "ねえ、あの日のこと、まだ覚えてる？",
        "うん、そうだよね。",
        "でもね、そのおかげで、{me}は「人にやさしくすること」の大切さを知ったんだ。"
        "うまくいかない人の気持ちが、わかるようになったからね。"
        "そのあと、まわりの人から頼りにされることが増えて、思ってもみなかった役目をもらうこともあったよ。"
        "今の{me}は、まだまだ勉強中だけど、毎日がわりと好きだよ。"
        "あの日の出来事は、今では、大切な思い出のひとつになっている。"
        "だから、{you}は{you}のままで進んでいってね。少しずつでいいんだよ。"
        "遠い未来から、ずっと応援しているよ。じゃあ、またね。"),
]

SERIOUS: list[Template] = [
    Template(_S_SERIOUS,
        _OPEN + "今日は、{you}の話を聞いたよ。…とてもつらいことだったよね。"
        "むりに元気を出さなくていいし、この気持ちに、いい意味や理由を探さなくていいんだよ。",
        "……聞こえてる？",
        "…うん。ゆっくりでいいよ。",
        "悲しいものは悲しいし、苦しいものは苦しい。それでいいんだ。"
        "{me}はね、その苦しいなかでも、{you}が毎日をなんとか生きてきたことを知っているよ。"
        "それだけで、本当にすごいことなんだ。"
        "{N}年たった今も、思い出すと胸がいたむ日はあるよ。でも、ひとりぼっちじゃなくなった。"
        "話を聞いてくれる人や、ほっとできる場所が、少しずつ見つかったんだ。"
        "だから、つらいときは、信じられる人に話してみてね。{you}が、今ここにいてくれること、それがなによりうれしいよ。"
        "{you}は、ひとりじゃないからね。じゃあ、またね。"),
    Template(_S_SERIOUS,
        _OPEN + "{you}の話、しずかに聞いていたよ。話してくれて、ありがとう。"
        "あのときの{you}は、たくさん傷ついて、心がくたくただったよね。",
        "……ちゃんと、聞こえてる？",
        "…うん。それでいいよ。",
        "{me}は、その痛みをなかったことにしたくないんだ。"
        "がんばらなくていいし、早く元気にならなくてもいい。"
        "泣きたいときは泣いて、休みたいときは休んでいいんだよ。"
        "{N}年後の{me}は、まだ生きているよ。うれしいことも、ときどきある。"
        "それは、{you}が、つらい日々のなかでも、今日まで歩いてきてくれたからなんだ。"
        "今、{you}がここにいること。それだけで、{me}は心からありがたいと思っているよ。"
        "もし苦しくなったら、家族や先生、信頼できる人に、その気持ちを少しだけ話してみてね。"
        "{me}は、いつでも{you}の味方だよ。じゃあ、またね。"),
    Template(_S_SERIOUS,
        _OPEN + "さっきの話を聞いて、{me}まで胸がぎゅっとなったよ。"
        "とても大きくて、重いできごとだったよね。そのなかで、よくここまで来たね。",
        "…今、そこにいてくれてるかな？",
        "…うん、ありがとう。",
        "あのことは、{you}のせいじゃないよ。そして、かんたんに乗りこえなくても大丈夫。"
        "時間がかかっても、ゆっくり、ゆっくりでいいんだ。"
        "{N}年後の{me}は、今も生きているよ。ごはんがおいしいと思える日も、空がきれいだなと思える日もある。"
        "そう思える日が来るなんて、あのころは信じられなかったけどね。"
        "だから、今日をこえたこと、それだけでいいんだよ。"
        "つらくなったら、ひとりでかかえこまずに、そばにいる人に声をかけてみてね。"
        "{you}が生きていてくれて、ありがとう。じゃあ、またね。"),
]

# v1 互換: 問いかけ 1 つの完全な本文(文字列)のリスト
GENERIC_TEMPLATES: list[str] = [t.full_text() for t in GENERIC]
SERIOUS_TEMPLATES: list[str] = [t.full_text() for t in SERIOUS]

_YOU_BY_FP = {"ぼく": "君", "おれ": "君", "わたし": "あなた", "あたし": "あなた", "うち": "あなた"}


def address_for(first_person: str) -> str:
    """一人称に合わせた呼びかけ(君/あなた)。"""
    return _YOU_BY_FP.get(first_person, "あなた")


def _pool(serious: bool) -> list[Template]:
    return SERIOUS if serious else GENERIC


_TRIGGERS = ("失敗", "緊張", "負け", "間違", "まちが", "忘れ", "落ち", "落と", "遅刻", "泣", "外し", "外れ", "ミス")
_TOPIC_HINT = re.compile(r"会|祭|試合|試験|大会|発表|テスト|練習|面接|受験|運転|免許|演奏|本番|旅行|授業|コンクール|オーディション|キック|シュート")
_NAME_SUFFIX = re.compile(r"^(さん|くん|ちゃん|君|氏|先輩|様)")
_BAD_CHARS = re.compile(r"[\d０-９A-Za-zＡ-Ｚａ-ｚ「」『』()（）\[\]【】<>＜＞/:@#＠]")
_MAX_EPISODE = 12
_EP_HEAD = ["{ep}のこと、{me}はよく覚えているよ。", "あの{ep}でうまくいかなくて…、って話だったよね。"]
_EP_QUESTION = ["ねえ、{ep}のこと、覚えてる？", "ねえ、{ep}のとき、どんな気持ちだった？"]
_EP_TAIL = ["{ep}のことも、今ではちゃんと思い出になっているよ。", "あの{ep}があったから、今の{me}がいるんだよ。"]


def _ok_phrase(p: str) -> bool:
    return 2 <= len(p) <= _MAX_EPISODE and not _BAD_CHARS.search(p) and not any(t in p for t in _TRIGGERS)


def extract_episode_phrase(transcript: str) -> str | None:
    """体験談から「〜のこと」に差し込める短い名詞句(例: 音楽会の伴奏)を 1 つ取り出す。LLM 不使用。

    保守的: 数字・英字・かっこ・URL を含む、人名らしい(さん/くん等が続く)、動詞の一部らしい
    ものは採らない。自信がなければ None(呼び出し側は汎用の文面にする)。
    """
    t = re.sub(r"\s+", "", transcript or "")
    if len(t) < 6 or re.search(r"https?:|www\.|@", t):
        return None
    if re.search(r"[一-龥ァ-ヶぁ-ん]{1,4}(さん|くん|ちゃん|君|先輩)", t):
        return None  # 人名らしきものがある話は差し込まない
    runs = list(re.finditer(r"[一-龥々ァ-ヶー]{2,}", t))
    cands: list[tuple[int, int, str]] = []  # (score, 長さ, phrase)
    valid = set(content_runs(t))
    for i, m in enumerate(runs):
        run = m.group()
        if run not in valid or len(run) > 8 or run.endswith(("ー", "々")) and len(run) < 3:
            continue
        after = t[m.end():m.end() + 3]
        if _NAME_SUFFIX.match(after):
            continue  # 人名らしい
        # 直後が送りがな(動詞・形容詞の語幹らしい): 例「間違えた」「忘れて」は除外
        if re.match(r"^[ぁ-ん]", after) and not re.match(r"^(の|で|に|を|は|が|と|も|へ|から|まで|や)", after):
            continue
        phrase = run
        # 「X の Y」の形なら X の Y にまとめる
        if i > 0 and runs[i - 1].end() + 1 == m.start() and t[runs[i - 1].end()] == "の" \
                and runs[i - 1].group() in valid and len(runs[i - 1].group()) <= 6:
            phrase = runs[i - 1].group() + "の" + run
        if not _ok_phrase(phrase):
            continue
        score = 0
        if _TOPIC_HINT.search(run):
            score += 3
        near = t[m.end():m.end() + 12]
        if any(k in near for k in _TRIGGERS):
            score += 2
        if re.fullmatch(r"[ァ-ヶー]{3,}", run):
            score += 1
        if score >= 3:  # 場面らしい語、またはカタカナ語+失敗語の近接だけ採る
            cands.append((score, len(phrase), phrase))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][2]


def pick_template_parts(future_years: int, first_person: str = "わたし",
                        serious: bool = False,
                        reply_pauses: int = 1,
                        rng: random.Random | None = None,
                        episode: str | None = None) -> tuple[str, list[tuple[str, bool]]]:
    """(style, [(パート本文, wait_for_reply), ...]) を返す。

    reply_pauses=0 なら 1 パート(問いかけ・相づちなし)、1 以上は 2 パート(2 問は 1 問に丸める)。
    episode(短い名詞句)があり、深刻でなければ「{episode}のこと」を共感・問いかけ・転機に差し込む。
    深刻テンプレートでは詳細を引用しない(episode は無視)。
    """
    r = rng or random
    t = r.choice(_pool(serious))
    kw = dict(N=future_years, me=first_person or "わたし", you=address_for(first_person))
    head, question, ack, tail = t.head, t.question, t.ack, t.tail
    ep = (episode or "").strip()
    if ep and not serious and _ok_phrase(ep) and "{" not in ep and "}" not in ep:
        head = head + r.choice(_EP_HEAD).replace("{ep}", ep)
        question = r.choice(_EP_QUESTION).replace("{ep}", ep)
        tail = r.choice(_EP_TAIL).replace("{ep}", ep) + tail
    if int(reply_pauses) <= 0:
        return t.style, [((head + tail).format(**kw), False)]
    return t.style, [((head + question).format(**kw), True),
                     ((ack + tail).format(**kw), False)]


def pick_template(future_years: int, first_person: str = "わたし",
                  serious: bool = False,
                  rng: random.Random | None = None) -> str:
    """条件に合うテンプレートをランダムに選び、年数・一人称を埋めた本文(問いかけ 1 つ)を返す。"""
    _, parts = pick_template_parts(future_years, first_person, serious, 1, rng)
    return "".join(t for t, _ in parts)
