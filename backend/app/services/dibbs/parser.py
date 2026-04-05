def parse_rfq_table(page):
    rows = page.query_selector_all("table tr")

    parsed = []

    for row in rows[1:]:
        cols = row.query_selector_all("td")

        if len(cols) < 5:
            continue

        try:
            link = cols[0].query_selector("a")

            parsed.append({
                "solicitation_number": cols[0].inner_text().strip(),
                "title": cols[1].inner_text().strip(),
                "agency": "DLA (DIBBS)",
                "url": link.get_attribute("href") if link else None,
                "source": "DIBBS"
            })
        except:
            continue

    return parsed