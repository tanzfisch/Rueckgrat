import re
from collections import Counter
from bs4 import BeautifulSoup

# content filter: pure helpers that keep the content of a fetched page and strip the noise around it
# (cookie banners, ads, menus, footers, repeated lines). no network, no llm, so they can be tested offline (hub/tests/test_content_filter.py)

NOISE_TAGS = ["script", "style", "noscript", "iframe", "form", "nav", "header", "footer", "aside", "svg"]
NOISE_ATTR = re.compile(r"cookie|consent|gdpr|banner|advert|\bads?\b|sponsor|promo|newsletter|subscribe|"
                        r"social|share|breadcrumb|menu|navbar|sidebar|footer|related|comment|popup|modal", re.IGNORECASE)
NOISE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search"}

NOISE_LINE = re.compile(r"cookie|consent|accept all|privacy policy|terms of (use|service)|all rights reserved|©|"
                        r"subscribe|newsletter|sign in|log ?in|advertisement|sponsored|share (on|this)|"
                        r"follow us|skip to (main )?content|read more|related (articles|posts)", re.IGNORECASE)
SHORT_LINE_WORDS = 25   # only lines shorter than this can be dropped by keyword, so real paragraphs survive
MAX_REPEATS = 3         # a line that shows up this often is a menu / footer item, not content


def _is_noise_element(tag) -> bool:
    attrs = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
    return bool(NOISE_ATTR.search(attrs)) or tag.get("role") in NOISE_ROLES or tag.get("aria-hidden") == "true"


def strip_html_boilerplate(html: str) -> str:
    """DOM level cleanup: prefer <main>/<article>/<body>, delete known non content elements, return the text"""
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("main") or soup.find("article") or soup.body or soup

    for tag in root.find_all(NOISE_TAGS):
        if not tag.decomposed:          # may be gone already, as a child of an earlier match
            tag.decompose()

    # collect first, decompose after: decomposing while find_all walks the tree would visit dead children
    noise = [tag for tag in root.find_all(True) if _is_noise_element(tag)]
    for tag in noise:
        if not tag.decomposed:
            tag.decompose()

    return root.get_text("\n", strip=True)


def strip_text_noise(text: str, min_keep_ratio: float = 0.2) -> str:
    """text level cleanup: drop short boilerplate lines (cookie notice, "Sign in", "© 2026 ...") and repeated lines.
    returns the original text if less than min_keep_ratio of it would survive (the heuristics don't fit that page)"""
    text = text or ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    counts = Counter(lines)

    kept, seen = [], set()
    for line in lines:
        if len(line.split()) < SHORT_LINE_WORDS and NOISE_LINE.search(line):
            continue
        if counts[line] >= MAX_REPEATS or line in seen:
            continue
        seen.add(line)
        kept.append(line)

    cleaned = "\n".join(kept)
    return cleaned if len(cleaned) >= min_keep_ratio * len(text) else text
