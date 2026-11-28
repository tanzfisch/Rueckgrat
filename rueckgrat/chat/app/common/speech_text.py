import re


class SpeechText:
    """the spoken form of a text: a chat reply, or a written text (a book, a story: the text_to_speech tool)"""
    _LINK = re.compile(r"https?://\S+|www\.\S+")
    _BLOCK_MARKER = re.compile(r"^\s*(?:#{1,6}|[-*+>]|\d+[.)])\s+")    # a markdown heading, list item or quote
    _SENTENCE_END = (".", "!", "?", "…", ":", ";")

    def __init__(self, text: str):
        self._text = text

    def without_code(self, complete: bool = True) -> str:
        """text without its ``` code blocks. complete False (still streaming): also cut at a block that is not closed yet,
        so the result of a growing text only grows"""
        text = re.sub(r"```.*?```", " ", self._text, flags=re.DOTALL)
        if not complete and "```" in text:
            text = text[:text.index("```")]
        return text

    def reply(self) -> str:
        """what of a chat reply is spoken: no code, *actions*, (asides), [tags], links or markdown stars"""
        text = self.without_code()
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)   # **bold** is spoken, a single *action* is not
        text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
        text = self._LINK.sub("", text)
        return " ".join(text.replace("*", "").split())

    def written(self) -> str:
        """what of a written text (a book, a story: the text_to_speech tool) is spoken: every word, without code, links and
        markdown markers. (asides) stay as they are, *emphasis* and [tags] keep their words, [text](link) its text. a heading,
        a list item or the last line before a blank line gets a period when it has no sentence end, so it is a sentence of
        its own and not run into the next one"""
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", self.without_code())
        lines = text.splitlines()
        spoken = []
        for i, line in enumerate(lines):
            block = bool(self._BLOCK_MARKER.match(line))
            line = self._LINK.sub("", self._BLOCK_MARKER.sub("", line))
            line = re.sub(r"(?<!\w)_+|_+(?!\w)", "", re.sub(r"[*`\[\]]", "", line))   # _emphasis_ markers, not snake_case
            line = " ".join(line.split())
            if line and (block or i + 1 == len(lines) or not lines[i + 1].strip()) and not line.rstrip("\"')»“”’").endswith(self._SENTENCE_END):
                line += "."
            if line:
                spoken.append(line)
        return " ".join(spoken)
