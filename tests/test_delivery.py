from app.bot.delivery import split_reply


def test_reply_split_is_lossless_and_within_telegram_limits():
    text = ("Assumption: 🍎 яблоко\n" * 1000) + "final assumption"
    chunks = split_reply(text)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 4000 for chunk in chunks)


def test_single_oversized_line_and_short_message():
    assert split_reply("short") == ["short"]
    chunks = split_reply("🍎" * 5000)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks) == "🍎" * 5000
