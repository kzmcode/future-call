from app.text_norm import (detect_first_person, int_to_kanji, normalize_for_tts,
                           split_parts_for_playback, split_sentences)


def test_int_to_kanji():
    assert int_to_kanji(10) == "十"
    assert int_to_kanji(2024) == "二千二十四"
    assert int_to_kanji(10000) == "一万"
    assert int_to_kanji(100) == "百"
    assert int_to_kanji(0) == "零"


def test_numbers_and_width():
    assert normalize_for_tts("10年後の自分") == "十年後の自分。"
    assert "三点五" in normalize_for_tts("3.5倍")
    assert "十" in normalize_for_tts("１０人")  # 全角
    assert "千二百" in normalize_for_tts("1,200円")


def test_symbols_markdown_emoji():
    out = normalize_for_tts("**やったね**😀 (すごい) 「うれしい」 #タグ")
    for ch in "*😀()「」#":
        assert ch not in out
    assert "やったね" in out and "うれしい" in out


def test_english():
    out = normalize_for_tts("LINEでOKって言われた")
    assert "ライン" in out and "オーケー" in out
    assert not any(c.isascii() and c.isalpha() for c in normalize_for_tts("xyzzy foo"))


def test_ending_punct_and_whitespace():
    assert normalize_for_tts("こんにちは   世界") == "こんにちは世界。"
    assert normalize_for_tts("だいじょうぶ！") == "だいじょうぶ！"
    assert normalize_for_tts("") == ""


def test_split_first_chunk_short_and_merge():
    text = "もしもし、びっくりしたよね。十年後のわたしだよ。あのね。うん。" + "とても長い文章がここに続いていくよ、" * 3 + "おわり。"
    chunks = split_sentences(text)
    assert chunks[0] == "もしもし、びっくりしたよね。"
    assert "".join(chunks) == text
    assert all(len(c) <= 80 for c in chunks)
    # 短い文は結合されている
    assert len(chunks[1]) >= 10


def test_split_newlines_and_empty():
    assert split_sentences("") == []
    assert split_sentences("あいうえおかきくけこ\nさしすせそたちつてと") == ["あいうえおかきくけこ", "さしすせそたちつてと"]


def test_detect_first_person():
    assert detect_first_person("僕は昨日テストで失敗した。僕なんて") == "ぼく"
    assert detect_first_person("俺、負けたんだ") == "おれ"
    assert detect_first_person("私は発表でとちった") == "わたし"
    assert detect_first_person("あたしね、転んだの") == "あたし"
    assert detect_first_person("転んだ") == "わたし"
    assert detect_first_person("") == "わたし"


def test_keeps_ellipsis_and_question():
    out = normalize_for_tts("えっとね…あはは、10年後だよ...ねえ、覚えてる?…そっか。")
    assert "…" in out and "？" in out and "十年後" in out and "..." not in out
    assert normalize_for_tts("うん…") == "うん…"
    assert normalize_for_tts("ほんと?") == "ほんと？"


def test_melo_variant_drops_ellipsis_keeps_question():
    out = normalize_for_tts("えっとね…そっか。ねえ、覚えてる?", keep_pauses=False)
    assert "…" not in out and "？" in out
    sents = split_parts_for_playback("えっとね…そっか。ねえ、覚えてる?…うん。")
    assert sents and all("…" not in s for s in sents)
