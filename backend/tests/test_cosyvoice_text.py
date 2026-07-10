from scripts.cosyvoice_text import split_tts_text


def test_split_tts_text_keeps_short_text_as_one_segment():
    assert split_tts_text("好的。", max_chars=20) == ["好的。"]


def test_split_tts_text_prefers_sentence_boundaries():
    text = "第一句很短。第二句也不长！第三句继续。"

    assert split_tts_text(text, max_chars=12) == ["第一句很短。", "第二句也不长！", "第三句继续。"]


def test_split_tts_text_splits_long_sentence_without_dropping_characters():
    text = "这是一段没有明显停顿但确实比较长的中文文本"

    segments = split_tts_text(text, max_chars=8)

    assert segments == ["这是一段没有明显", "停顿但确实比较长", "的中文文本"]
    assert "".join(segments) == text
