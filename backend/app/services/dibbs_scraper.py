from bs4 import BeautifulSoup


def _safe(x):
    return (x or "").strip()


def _is_valid_detail_url(url: str | None) -> bool:
    url = _safe(url)
    if not url:
        return False

    upper = url.upper()
    return "RFQNSN.ASPX" in upper or "RFQSOL.ASPX" in upper


def parse_dibbs_list(html: str):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for link in soup.select("a"):
        href = link.get("href")
        text = link.get_text(strip=True)

        if not _is_valid_detail_url(href):
            continue

        rows.append({
            "title": text,
            "url": href,
            "solicitation": text,
        })

    return rows
