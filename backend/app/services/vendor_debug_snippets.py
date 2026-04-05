"""
READY-TO-PASTE DEBUG SNIPPETS for your vendor service file.
Use these in whichever service/module currently handles:
- syncing vendor leads
- seeding vendor quotes
"""

# ===== START: add near the top of your vendor lead sync function =====
print(f"[VENDOR DEBUG] syncing leads for opportunity_id={opportunity_id}")
print(f"[VENDOR DEBUG] parsed approved_sources={len(parsed.get('approved_sources') or [])}")
# ===== END =====


# ===== START: add inside the loop that creates or updates vendor leads =====
print(
    "[VENDOR DEBUG] lead candidate:",
    {
        "company_name": company_name,
        "cage": cage,
        "part_number": part_number,
        "nsn": nsn,
        "raw_text": raw_text,
    }
)
# ===== END =====


# ===== START: add after commit in the vendor lead sync function =====
print(f"[VENDOR DEBUG] total leads after sync={len(created_or_updated)}")
# ===== END =====


# ===== START: add near the top of your quote seeding function =====
print(f"[QUOTE DEBUG] seeding quotes for opportunity_id={opportunity_id}")
print(f"[QUOTE DEBUG] seedable leads count={len(seedable_leads)}")
# ===== END =====


# ===== START: add inside the loop that seeds quotes =====
print(
    "[QUOTE DEBUG] quote seed candidate:",
    {
        "company_name": lead.company_name,
        "cage": lead.cage,
        "part_number": lead.part_number,
    }
)
# ===== END =====


# ===== START: add after commit in the quote seeding function =====
print(f"[QUOTE DEBUG] quotes created={created_count}")
# ===== END =====
