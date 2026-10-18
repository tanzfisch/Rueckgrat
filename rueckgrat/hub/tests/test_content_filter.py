"""offline tests for app/utils/content_filter.py, no network, no llm.
run from rueckgrat/hub:  python -m pytest tests/test_content_filter.py -v   (or: python tests/test_content_filter.py)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.utils.content_filter import strip_html_boilerplate, strip_text_noise

ARTICLE = ("The city council approved the new harbour bridge on Tuesday after three years of planning. "
           "Construction is expected to start next spring and to take about two years to complete.")

PAGE = f"""<html><body>
<div id="cookie-consent">We use cookies to improve your experience. Accept all</div>
<nav><a href="/">Home</a><a href="/news">News</a></nav>
<header><h1>Daily Paper</h1></header>
<div class="ad-slot">Buy cheap watches now</div>
<main>
  <ul class="breadcrumb"><li>Home</li><li>Local</li></ul>
  <article>
    <h2>Harbour bridge approved</h2>
    <p>{ARTICLE}</p>
    <div class="share-buttons">Share on Facebook</div>
    <aside>Related stories you might like</aside>
    <div role="complementary">Most read today</div>
    <div aria-hidden="true">hidden decoration</div>
  </article>
  <div class="newsletter-box"><form>Subscribe to our newsletter</form></div>
</main>
<footer>© 2026 Daily Paper. All rights reserved.</footer>
<script>trackVisitor();</script>
</body></html>"""


def test_html_keeps_article_text():
    text = strip_html_boilerplate(PAGE)
    assert "Harbour bridge approved" in text
    assert ARTICLE in text


def test_html_removes_noise():
    text = strip_html_boilerplate(PAGE)
    for noise in ["cookies", "Home", "Daily Paper", "cheap watches", "Share on", "Related stories",
                  "Most read", "hidden decoration", "newsletter", "All rights reserved", "trackVisitor"]:
        assert noise not in text, f"'{noise}' should be removed:\n{text}"


def test_html_nested_noise_does_not_crash():
    # a noise element inside another noise element is gone with its parent before the loop reaches it
    html = '<body><div class="sidebar"><div class="promo"><nav>x</nav></div></div><p>content</p></body>'
    assert strip_html_boilerplate(html) == "content"


def test_html_without_main_uses_body():
    html = f"<html><body><nav>Menu</nav><p>{ARTICLE}</p><footer>Imprint</footer></body></html>"
    assert strip_html_boilerplate(html) == ARTICLE


def test_text_drops_short_noise_lines():
    text = "\n".join(["Skip to content", "Sign in", ARTICLE, "This site uses cookies. Accept all", "© 2026 Example Ltd"])
    assert strip_text_noise(text) == ARTICLE


def test_text_keeps_long_lines_with_noise_words():
    # a real paragraph that mentions "cookie" is 25+ words, so it must survive
    long_line = ("The bakery on Queen Street sells a famous chocolate cookie that people queue for every morning, "
                 "and the owner says the recipe has not changed since her grandmother opened the shop in 1952.")
    assert len(long_line.split()) >= 25
    assert long_line in strip_text_noise(long_line + "\n" + ARTICLE)


def test_text_removes_repeated_lines():
    text = "\n".join(["Home | News | Sport", ARTICLE, "Home | News | Sport", "Second paragraph about the bridge.",
                      "Home | News | Sport", "Second paragraph about the bridge."])
    cleaned = strip_text_noise(text).splitlines()
    assert "Home | News | Sport" not in cleaned                              # 3 times -> menu, dropped
    assert cleaned.count("Second paragraph about the bridge.") == 1          # duplicate -> only the first kept
    assert ARTICLE in cleaned


def test_text_normalizes_whitespace():
    assert strip_text_noise("  The   bridge \t was approved.  \n\n") == "The bridge was approved."


def test_text_fallback_returns_original():
    # everything matches the noise patterns -> less than 20% survives -> original text back
    text = "Accept all cookies\nSign in\nSubscribe to our newsletter\nPrivacy policy"
    assert strip_text_noise(text) == text


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
