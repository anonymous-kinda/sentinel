"""The quad chart is one letter-size page in system fonts, has the four
standard quadrants, and states no number that the repository did not
generate or that the allowlist does not explain.
"""

import re
import xml.etree.ElementTree as ET

from sentinel.ai.grounding import check_grounding

from .doccheck import DOCS, QUAD_CHART_SVG, ROOT, generated_text, svg_texts

QUAD_CHART_MD = DOCS / "quad-chart.md"
QUADRANTS = (
    "Operational capability",
    "Technical approach and discriminators",
    "Status and milestones",
    "Evidence and next steps",
)

# Numbers on the chart that no generated report states. Each names the file
# it comes from, the exact phrase there, and why it is on the chart. Nothing
# here is estimated.
ALLOWED = {
    "17.50": ("docs/deploy-aws.md", "about $17.50/month",
              "the AWS demo hub's monthly cost, as the deploy guide states it"),
    "37": ("docs/compliance.md", "Tailored baseline: **37** controls.",
           "controls in the tailored baseline; tests/compliance/test_package_integrity.py checks the count"),
    "9": ("docs/compliance.md", "**9** implemented controls",
          "controls implemented; checked by the same test"),
    "28": ("docs/compliance.md", "**28** partial controls",
           "controls partly implemented; checked by the same test"),
}

LETTER_LANDSCAPE_IN = (11.0, 8.5)
MIN_POINT_SIZE = 9.0
SYSTEM_FONTS = {
    "system-ui", "-apple-system", "blinkmacsystemfont", "segoe ui", "roboto", "helvetica neue",
    "helvetica", "arial", "liberation sans", "dejavu sans", "sans-serif",
    "ui-monospace", "sf mono", "menlo", "consolas", "liberation mono", "dejavu sans mono", "monospace",
}


def chart_number_problems(texts: list[str], evidence: str) -> list[str]:
    """Numbers on the chart that neither the evidence nor the allowlist states (ADR-007's grounding rule)."""
    return check_grounding("\n".join(texts), "\n".join([evidence, *ALLOWED])).unsupported


def font_problems(svg: str) -> list[str]:
    families = re.findall(r"font-family\s*:\s*([^;}]+)", svg) + re.findall(r'font-family="([^"]*)"', svg)
    fonts = {f.strip().strip("'\"").lower() for decl in families for f in decl.split(",")}
    remote = re.findall(r"@font-face|@import|url\((?!#)|(?:href|src)\s*=\s*\"(?!#)", svg)
    return sorted(fonts - SYSTEM_FONTS) + remote


def smallest_point_size(svg: str) -> float:
    root = ET.fromstring(svg)
    width_in, height_in = (float(root.get(a).removesuffix("in")) for a in ("width", "height"))
    _, _, vb_width, vb_height = (float(v) for v in root.get("viewBox").split())
    assert (width_in, height_in) == LETTER_LANDSCAPE_IN
    assert abs(vb_width / vb_height - width_in / height_in) < 1e-9, "the viewBox keeps the page's shape"
    points_per_unit = width_in * 72 / vb_width
    sizes = [float(s) for s in re.findall(r"font-size\s*[:=]\s*\"?([\d.]+)", svg)]
    return min(sizes) * points_per_unit


# --------------------------------------------------------- the checks catch it


def test_a_number_no_report_states_is_caught():
    texts = ["53 events", "about $18.25 a month", "$17.50 a month"]
    assert chart_number_problems(texts, "53 operational events") == ["18.25"]


def test_a_web_font_or_remote_resource_is_caught():
    svg = '<style>@import "x.css"; .a { font-family: "Inter", Arial, sans-serif }</style><image href="https://x/y.png"/>'
    assert font_problems(svg) == ["inter", "@import", 'href="']


def test_small_type_is_caught():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="11in" height="8.5in" viewBox="0 0 1100 850">'
           "<style>.a { font-size: 10px }</style></svg>")
    assert smallest_point_size(svg) < MIN_POINT_SIZE


# ------------------------------------------------------------ the real chart


def test_the_chart_is_an_svg_document_with_a_title():
    root = ET.parse(QUAD_CHART_SVG).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.find("{http://www.w3.org/2000/svg}title").text.strip()


def test_the_four_quadrant_titles_are_on_the_chart():
    texts = svg_texts(QUAD_CHART_SVG)
    assert [q for q in QUADRANTS if q not in texts] == []


def test_every_number_on_the_chart_is_generated_or_allowlisted():
    assert chart_number_problems(svg_texts(QUAD_CHART_SVG), generated_text()) == []


def allowlist_problems(allowed: dict) -> list[str]:
    problems = []
    for number, (source, phrase, reason) in allowed.items():
        text = " ".join((ROOT / source).read_text(encoding="utf-8").split())
        if not reason or phrase not in text or number not in phrase:
            problems.append(number)
    return problems


def test_an_allowlisted_number_its_file_does_not_state_is_caught():
    wrong = {
        "18.25": ("docs/deploy-aws.md", "about $18.25/month", "a cost the guide does not state"),
        "37": ("docs/compliance.md", "Tailored baseline: **37** controls.", ""),
        "12": ("docs/compliance.md", "Tailored baseline: **37** controls.", "number not in its phrase"),
    }
    assert allowlist_problems(wrong) == ["18.25", "37", "12"]


def test_every_allowlisted_number_is_in_the_file_it_cites():
    assert allowlist_problems(ALLOWED) == []


def test_letter_size_system_fonts_and_legible_type():
    svg = QUAD_CHART_SVG.read_text(encoding="utf-8")
    assert font_problems(svg) == []
    assert smallest_point_size(svg) >= MIN_POINT_SIZE


def test_the_markdown_page_embeds_the_chart_with_alt_text():
    alt = re.search(r"!\[([^\]]+)\]\(quad-chart\.svg\)", QUAD_CHART_MD.read_text(encoding="utf-8"))
    assert alt and len(alt.group(1).split()) >= 12, "alt text says what the chart shows"
