"""Lossless plain-text splitting with Telegram's UTF-16 length accounting."""


def split_reply(text: str, limit: int = 4000) -> list[str]:
    if limit < 2:
        raise ValueError("message limit must allow a Unicode code point")
    chunks: list[str] = []
    while text:
        units = 0
        end = 0
        last_break = 0
        for index, char in enumerate(text):
            width = 2 if ord(char) > 0xFFFF else 1
            if units + width > limit:
                break
            units += width
            end = index + 1
            if char == "\n":
                last_break = end
        if end < len(text) and last_break > end // 2:
            end = last_break
        chunks.append(text[:end])
        text = text[end:]
    return chunks
