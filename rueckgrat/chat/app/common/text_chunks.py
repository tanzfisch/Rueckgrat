import re

MIN_CHUNK_WORDS = 35
FIRST_CHUNK_WORDS = 15  # the first chunks of a reply are shorter, so its speech starts sooner, see chunk_words
CHUNK_WORDS_STEP = 5
ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "rev.", "gen.", "col.", "lt.", "capt.", "sgt.", "maj.", "adm.", "gov.", "pres.", "sen.", "rep.", "hon.", "st.",  # titles
    "u.s.", "u.k.", "u.n.", "e.u.", "f.b.i.", "c.i.a.", "n.s.a.", "i.r.s.", "f.d.a.", "e.p.a.", "f.t.c.", "f.c.c.", "f.a.a.", "d.o.d.", "d.o.j.", "d.o.e.", "d.o.l.", "d.o.s.", "d.o.t.", "d.o.i.",  # organisations
    "inc.", "ltd.", "corp.", "co.", "assn.", "univ.", "dept.", "govt.", "conf.",  # business
    "ph.d.", "m.d.", "d.o.", "j.d.", "ed.d.", "m.a.", "b.a.", "m.s.", "b.s.", "m.b.a.", "m.sc.", "b.sc.", "m.ed.", "b.ed.", "m.s.w.", "m.p.h.", "m.p.a.", "ll.b.", "ll.m.", "psy.d.", "pharm.d.", "d.n.p.", "r.n.", "l.p.n.",  # academic
    "vol.", "no.", "fig.", "ch.", "sec.", "pp.", "p.", "ed.", "eds.", "approx.", "est.", "max.", "min.", "avg.",  # publishing
    "a.m.", "p.m.", "a.d.", "b.c.", "ca.",  # time
    "vs.", "etc.", "e.g.", "i.e.", "viz.", "nos.", "fl.", "oz.", "lb.", "kg.", "cm.", "mm.", "km.", "mph.", "rpm.",  # general
    "z.b.", "bzw.", "usw.", "nr.", "str.",  # german
}


def chunk_words(index: int) -> int:
    """the minimum words of a reply's chunk: they grow by CHUNK_WORDS_STEP from FIRST_CHUNK_WORDS up to MIN_CHUNK_WORDS,
    so each chunk's speech is generated while the shorter one before it plays"""
    return min(MIN_CHUNK_WORDS, FIRST_CHUNK_WORDS + CHUNK_WORDS_STEP * index)


def split_into_chunks(text: str, min_words: int = MIN_CHUNK_WORDS, max_words: int | None = None) -> list[str]:
    chunks, words = [], []
    for word in text.split():
        words.append(word)
        end = word.rstrip("\"')]»“”’")
        sentence_end = end.endswith((".", "!", "?", "…")) and end.lower() not in ABBREVIATIONS \
            and not re.fullmatch(r"[A-Za-z]\.|\d[\d.]*\.", end)
        if (len(words) >= min_words and sentence_end) or (max_words and len(words) >= max_words):
            chunks.append(" ".join(words))
            words = []
    if words:
        chunks.append(" ".join(words))
    return chunks


def without_code(text: str, complete: bool = True) -> str:
    """text without its ``` code blocks. complete False (still streaming): also cut at a block that is not closed yet,
    so the result of a growing text only grows"""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    if not complete and "```" in text:
        text = text[:text.index("```")]
    return text


LINK = re.compile(r"https?://\S+|www\.\S+")
BLOCK_MARKER = re.compile(r"^\s*(?:#{1,6}|[-*+>]|\d+[.)])\s+")    # a markdown heading, list item or quote
SENTENCE_END = (".", "!", "?", "…", ":", ";")


def speech_text(text: str) -> str:
    """what of a chat reply is spoken: no code, *actions*, (asides), [tags], links or markdown stars"""
    text = without_code(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)   # **bold** is spoken, a single *action* is not
    text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
    text = LINK.sub("", text)
    return " ".join(text.replace("*", "").split())


def written_speech_text(text: str) -> str:
    """what of a written text (a book, a story: the text_to_speech tool) is spoken: every word, without code, links and
    markdown markers. (asides) stay as they are, *emphasis* and [tags] keep their words, [text](link) its text. a heading,
    a list item or the last line before a blank line gets a period when it has no sentence end, so it is a sentence of
    its own and not run into the next one"""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", without_code(text))
    lines = text.splitlines()
    spoken = []
    for i, line in enumerate(lines):
        block = bool(BLOCK_MARKER.match(line))
        line = LINK.sub("", BLOCK_MARKER.sub("", line))
        line = re.sub(r"(?<!\w)_+|_+(?!\w)", "", re.sub(r"[*`\[\]]", "", line))   # _emphasis_ markers, not snake_case
        line = " ".join(line.split())
        if line and (block or i + 1 == len(lines) or not lines[i + 1].strip()) and not line.rstrip("\"')»“”’").endswith(SENTENCE_END):
            line += "."
        if line:
            spoken.append(line)
    return " ".join(spoken)
