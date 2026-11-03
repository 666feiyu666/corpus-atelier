"""The product's single injected stylesheet: type, rules, and quiet chrome.

Streamlit owns the widget markup, so the visual identity lives here rather than
in per-view inline styles: one serif display family for names and headings, one
sans family for interface text, hairline rules instead of card shadows, and one
indigo accent shared by the current tab and the primary action.
"""

from __future__ import annotations

import streamlit as st


SANS = (
    '"PingFang SC", "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei", '
    "system-ui, -apple-system, sans-serif"
)
MONO = '"JetBrains Mono", "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", monospace'

# Georgia carries Latin display text; the Song faces carry CJK display text. The
# unicode ranges keep each script on the face that was drawn for it.
DISPLAY_FACES = """
@font-face {
  font-family: "AtelierDisplay";
  src: local("Georgia"), local("Times New Roman"), local("Noto Serif");
  unicode-range: U+0000-024F, U+2000-206F, U+20A0-20CF, U+2100-21FF;
}
@font-face {
  font-family: "AtelierDisplay";
  src: local("Songti SC"), local("Noto Serif SC"),
       local("Source Han Serif SC"), local("SimSun");
  unicode-range: U+2E80-9FFF, U+F900-FAFF, U+FE30-FE4F, U+FF00-FFEF;
}
"""

STYLESHEET = f"""
<style>
{DISPLAY_FACES}

:root {{
  --atelier-ink: #16181A;
  --atelier-ink-soft: #5C6169;
  --atelier-paper: #FAFAF8;
  --atelier-paper-sunk: #F1F2EE;
  --atelier-rule: #DCDED8;
  --atelier-indigo: #2B4C7E;
  --atelier-display: "AtelierDisplay", Georgia, "Songti SC", serif;
}}

html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
.stMarkdown p, button, input, textarea, select, [data-testid="stWidgetLabel"] {{
  font-family: {SANS};
}}
code, pre, kbd, [data-testid="stCode"] code {{
  font-family: {MONO} !important;
}}

h1, h2, h3, h4,
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2,
[data-testid="stHeading"] h3, [data-testid="stHeading"] h4 {{
  font-family: var(--atelier-display) !important;
  letter-spacing: 0.01em;
}}
h1 {{ font-size: 30px !important; font-weight: 600; }}
h2 {{ font-size: 22px !important; font-weight: 600; }}
h3 {{ font-size: 17px !important; font-weight: 600; }}
h4 {{ font-size: 15px !important; font-weight: 600; }}
[data-testid="stMarkdownContainer"] p {{ line-height: 1.7; }}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{
  max-width: 74ch;
}}

/* The reading column stays centred and slightly narrow on wide screens. */
/* Streamlit's header is fixed at 56px and paints over the content when the
   sidebar is collapsed, so the reading column starts below it. */
[data-testid="stMainBlockContainer"] {{
  max-width: 1180px;
  margin: 0 auto;
  padding-top: 3.6rem;
}}

/* Top navigation: one wordmark, two quiet tabs, a single indigo rule. */
.atelier-wordmark {{
  font-family: var(--atelier-display);
  font-size: 20px;
  letter-spacing: 0.05em;
  color: var(--atelier-ink);
  padding-bottom: 0.45rem;
  white-space: nowrap;
}}
.st-key-product_view_tabs [data-testid="stWidgetLabel"] {{ display: none; }}
.st-key-product_view_tabs [role="radiogroup"] {{
  gap: 1.9rem;
  background: transparent;
  padding: 0;
}}
.st-key-product_view_tabs button[data-variant="segmented_control"] {{
  background: transparent !important;
  border: none;
  border-radius: 0;
  box-shadow: none;
  padding: 0.1rem 0 0.4rem;
  min-height: 0;
}}
.st-key-product_view_tabs button[aria-checked="true"] {{
  background: transparent !important;
  border-bottom: 2px solid var(--atelier-indigo);
}}
.st-key-product_view_tabs button[aria-checked="true"]:hover {{
  background: transparent !important;
}}
.st-key-product_view_tabs button[aria-checked="false"] p {{
  color: var(--atelier-ink-soft);
}}
.st-key-product_view_tabs button p {{ font-size: 15px; }}
.atelier-nav-rule {{
  border-top: 1px solid var(--atelier-rule);
  margin: 0.15rem 0 1.5rem;
}}

/* Sections read as sections: separators and type carry the hierarchy, not cards. */
[data-testid="stVerticalBlockBorderWrapper"] {{
  border-radius: 2px;
  box-shadow: none;
}}
[data-testid="stImage"] img {{
  border-radius: 2px;
}}
.st-key-gallery_grid [data-testid="stImage"] img {{
  height: 210px;
  width: 100%;
  object-fit: contain;
  background: var(--atelier-paper-sunk);
}}
.st-key-gallery_grid [data-testid="stMarkdownContainer"] strong {{
  font-family: var(--atelier-display);
  font-size: 15px;
  line-height: 1.45;
}}
.st-key-gallery_grid [data-testid="stCaptionContainer"] p {{
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}

/* The sidebar task list is a list, not a panel. */
.st-key-task_list {{
  background: transparent;
  border: none;
}}
.st-key-atelier_nav {{
  align-items: baseline;
}}

/* Focus stays visible for keyboard users. */
button:focus-visible, a:focus-visible, [role="radio"]:focus-visible,
input:focus-visible, textarea:focus-visible, [role="combobox"]:focus-visible {{
  outline: 2px solid var(--atelier-indigo);
  outline-offset: 2px;
}}

@media (max-width: 700px) {{
  .st-key-atelier_nav {{
    flex-wrap: wrap;
    row-gap: 0.35rem;
  }}
  .st-key-product_view_tabs [role="radiogroup"] {{
    gap: 1.1rem;
  }}
  .st-key-gallery_grid [data-testid="stImage"] img {{
    height: 160px;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }}
}}
</style>
"""


def inject_theme() -> None:
    """Inject the stylesheet once per rendered page."""
    st.html(STYLESHEET)
