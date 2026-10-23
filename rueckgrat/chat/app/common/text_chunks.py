import re

MIN_CHUNK_WORDS = 35
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


def split_into_chunks(text: str, min_words: int = MIN_CHUNK_WORDS) -> list[str]:
    """splits text into chunks of at least min_words words, a chunk only ends where a sentence ends
    (a word ending in . ! ? or …, not an abbreviation, an initial or a number like "12." or "12.10.").
    the last chunk takes the rest. decimals like 3.5 never end a sentence, there is no space after the dot"""
    chunks, words = [], []
    for word in text.split():
        words.append(word)
        end = word.rstrip("\"')]»“”’")
        sentence_end = end.endswith((".", "!", "?", "…")) and end.lower() not in ABBREVIATIONS \
            and not re.fullmatch(r"[A-Za-z]\.|\d[\d.]*\.", end)
        if len(words) >= min_words and sentence_end:
            chunks.append(" ".join(words))
            words = []
    if words:
        chunks.append(" ".join(words))
    return chunks
