import re

# code pasted into a user message without ``` gets fenced by the hub (main.py /ws receive), so every tool, the models and the bubble see where it starts and ends.
# conservative: a line only counts as code when it looks like code, a block is only fenced with at least two code lines
# and one sure sign (preprocessor, def/class/import, a declaration, braces, std::), text that has fences already is left alone.

_STRONG = [
    r"#\s*(include|define|ifndef|ifdef|endif|pragma)\b.*",                                # c/c++ preprocessor
    r"(def|class)\s+\w+.*:",                                                             # python definitions
    r"(import\s+[\w.]+(\s+as\s+\w+)?(\s*,\s*[\w.]+)*|from\s+[\w.]+\s+import\s+.+)",        # python imports
    r"(if|elif|else|for|while|try|except|finally|with)\b.*:",                            # python blocks
    r"(int|void|char|float|double|bool|auto|unsigned|long|const|let|var|function|public|private|static|struct|return)\b(.*[()=\[\]<>].*[;{}]|.*\{)",  # declarations, with a code character
    r".*\bstd::\w+.*",
    r".*[)\]=]\s*\{",                                                                    # main() {, if (x) {, x = {
    r"\}\s*(else\b.*)?;?",                                                               # closing brace
    r".*\b(console\.log|printf|cout|cin|System\.out\.\w+)\b.*;",
    r"(\}\s*)?(for|if|while|switch|else\s+if|catch)\s*\(.*\)",                            # c/js headers: for (...) without ; or {
    r"((unsigned|signed|const|static|inline|virtual)\s+)*(int|void|char|float|double|bool|auto|long|short|size_t|std::[\w:<>, ]+)[\s*&]+[\w:~]+\s*\([^;]*\)(\s*const)?",  # int main(), void f(int x)
]
_WEAK = [
    r".*[\w)\]\"'+-]\s*;",                                    # semicolon-terminated, prose needs a code character too (see below)
    r"[\w.\[\]]+\s*[-+*/%]?=\s*[^=\s].*",                     # assignment: x = 1, total += i
    r"[\w.]+\(.*\)\s*;?",                                     # a call on its own line: print(x)
    r"return\b.*",
    r"\{",
]
_CODE_CHARS = re.compile(r"[()=\[\]<>\"{}]|::")
_SINGLE = re.compile(r"\s*(#\s*include\s*[<\"].*|def\s+\w+\s*\(.*\)\s*:.*)")   # sure enough for a single line


def _strong(line: str) -> bool:
    s = line.strip()
    return any(re.fullmatch(p, s) for p in _STRONG)


def _weak(line: str) -> bool:
    s = line.strip()
    if not any(re.fullmatch(p, s) for p in _WEAK):
        return False
    return bool(_CODE_CHARS.search(s)) or s in ("{", "}") or re.fullmatch(r"(return|break|continue)\b.*;", s) is not None


def _language(code: str) -> str:
    if re.search(r"#\s*include|std::|\bcout\b|\bint\s+main\s*\(", code):
        return "cpp"
    if re.search(r"console\.log|\bfunction\b|=>|^\s*(const|let|var)\s+\w+\s*=", code, re.MULTILINE):
        return "js"
    if re.search(r"^\s*(def|class|import|from)\s|^\s*print\(|:\s*$", code, re.MULTILINE) and not re.search(r";\s*$", code, re.MULTILINE):
        return "python"
    return ""


def fence_code(text: str) -> str:
    """wraps unfenced code lines of a message in ``` fences (with cpp, python or js when obvious), the prose stays outside"""
    if not text or "```" in text:
        return text
    lines = text.split("\n")
    code = [_strong(l) or _weak(l) for l in lines]
    for i in range(1, len(lines)):   # indented lines and blank lines between code lines continue a block
        if not code[i] and code[i - 1] and re.match(r"(  +|\t)\S", lines[i]):
            code[i] = True
    for i in range(len(lines) - 1):   # a short line between code lines or before a "{" line joins, so a block isn't split
        s = lines[i].strip()
        if not code[i] and s and len(s) <= 80 and (_CODE_CHARS.search(s) or not re.search(r"[.!?,:;]$", s)) \
                and ((i > 0 and code[i - 1] and code[i + 1]) or lines[i + 1].strip().startswith("{")):
            code[i] = True
    for i in range(1, len(lines) - 1):
        if not lines[i].strip() and code[i - 1] and code[i + 1]:
            code[i] = True

    out, i = [], 0
    while i < len(lines):
        if not code[i]:
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and code[j]:
            j += 1
        block = lines[i:j]
        real = [l for l in block if l.strip()]
        if (len(real) >= 2 and any(_strong(l) for l in real)) or (len(real) == 1 and _SINGLE.fullmatch(real[0])):
            out += ["```" + _language("\n".join(block))] + block + ["```"]
        else:
            out += block
        i = j
    return "\n".join(out)
