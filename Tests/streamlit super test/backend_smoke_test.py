import json
import csv
import traceback
from pathlib import Path

import requests
from sqlalchemy import create_engine, text

API = "http://127.0.0.1:8000"
DATABASE_URL = "postgresql+psycopg://nagacon:nagacon@localhost:5432/nagacon"

OUT_DIR = Path("test_reports")
OUT_DIR.mkdir(exist_ok=True)

LIMIT = 25
SOURCE = "DIBBS"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text[:2000]}

def call(method, url, **kwargs):
    try:
        r = requests.request(method, url, timeout=1200, **kwargs)
        return {
            "ok": r.ok,
            "status_code": r.status_code,
            "json": safe_json(r),
            "text": r.text[:2000],
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "json": None,
            "text": str(e),
        }

def get_test_opportunities(limit=25, source="DIBBS"):
    sql = text("""
        SELECT id, solicitation_number, title, source, url
        FROM opportunities
        WHERE source = :source
        ORDER BY id DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"source": source, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]

def summarize_vendor_artifact(artifact_json):
    if not artifact_json:
        return {"vendor_count": 0, "has_vendors": False}
    content = artifact_json.get("content_json") or {}
    vendors = content.get("vendors") or []
    return {
        "vendor_count": len(vendors),
        "has_vendors": len(vendors) > 0,
    }

def summarize_files(files_json):
    out = {
        "file_count": 0,
        "official_pdf_count": 0,
        "snapshot_count": 0,
        "filenames": [],
    }
    if not isinstance(files_json, list):
        return out
    out["file_count"] = len(files_json)
    for f in files_json:
        ft = (f.get("file_type") or "").upper()
        fn = f.get("filename")
        if fn:
            out["filenames"].append(fn)
        if ft == "PDF_OFFICIAL":
            out["official_pdf_count"] += 1
        if ft in {"PDF_SNAPSHOT", "PDF_FALLBACK_SNAPSHOT"}:
            out["snapshot_count"] += 1
    return out

def main():
    opps = get_test_opportunities(limit=LIMIT, source=SOURCE)
    if not opps:
        print("No opportunities found.")
        return

    full_results = []
    csv_rows = []

    for idx, opp in enumerate(opps, start=1):
        opp_id = opp["id"]
        sol = opp["solicitation_number"]
        print(f"[{idx}/{len(opps)}] Testing opportunity {opp_id} - {sol}")

        result = {
            "opportunity": opp,
            "steps": {},
            "summary": {},
        }

        payload = {"opportunity_id": opp_id}

        # 1) Parse
        result["steps"]["parse"] = call("POST", f"{API}/api/workspace/parse", json=payload)

        # 2) Generate checklist
        result["steps"]["generate_checklist"] = call("POST", f"{API}/api/workspace/generate/checklist", json=payload)

        # 3) Generate vendors
        result["steps"]["generate_vendors"] = call("POST", f"{API}/api/workspace/generate/vendors", json=payload)

        # 4) Generate email
        result["steps"]["generate_email"] = call("POST", f"{API}/api/workspace/generate/email", json=payload)

        # 5) List artifacts
        result["steps"]["list_artifacts"] = call("GET", f"{API}/api/workspace/artifacts", params={"opp_id": opp_id})

        # 6) List tasks
        result["steps"]["list_tasks"] = call("GET", f"{API}/api/workspace/tasks", params={"opp_id": opp_id})

        # 7) Seed vendor quotes
        result["steps"]["seed_quotes"] = call("POST", f"{API}/api/vendors/quotes/seed", json={"opportunity_id": opp_id})

        # 8) Get vendor quotes
        result["steps"]["get_quotes"] = call("GET", f"{API}/api/vendors/quotes", params={"opportunity_id": opp_id})

        # 9) Download PDFs
        result["steps"]["download_pdfs"] = call(
            "POST",
            f"{API}/api/files/download_pdfs",
            params={
                "opportunity_id": opp_id,
                "always_snapshot": "true",
                "prefer_dibbs_solicitation_detail": "true",
            },
        )

        # 10) List files
        result["steps"]["list_files"] = call("GET", f"{API}/api/files/list", params={"opportunity_id": opp_id})

        # 11) Get submission
        result["steps"]["get_submission"] = call("GET", f"{API}/api/submissions", params={"opportunity_id": opp_id})

        # 12) Export bid package
        try:
            r = requests.get(f"{API}/api/export/bid_package", params={"opportunity_id": opp_id}, timeout=1200)
            result["steps"]["export_bid_package"] = {
                "ok": r.ok,
                "status_code": r.status_code,
                "content_type": r.headers.get("content-type"),
                "content_length": len(r.content or b""),
                "text": r.text[:500] if not r.ok else "",
            }
        except Exception as e:
            result["steps"]["export_bid_package"] = {
                "ok": False,
                "status_code": None,
                "content_type": None,
                "content_length": 0,
                "text": str(e),
            }

        vendor_art = result["steps"]["generate_vendors"]["json"] if result["steps"]["generate_vendors"]["ok"] else {}
        vendor_summary = summarize_vendor_artifact(vendor_art)

        files_json = result["steps"]["list_files"]["json"] if result["steps"]["list_files"]["ok"] else []
        file_summary = summarize_files(files_json)

        quotes_json = result["steps"]["get_quotes"]["json"] if result["steps"]["get_quotes"]["ok"] and isinstance(result["steps"]["get_quotes"]["json"], list) else []
        quotes_count = len(quotes_json)

        result["summary"] = {
            "parse_ok": result["steps"]["parse"]["ok"],
            "checklist_ok": result["steps"]["generate_checklist"]["ok"],
            "vendors_ok": result["steps"]["generate_vendors"]["ok"],
            "email_ok": result["steps"]["generate_email"]["ok"],
            "seed_quotes_ok": result["steps"]["seed_quotes"]["ok"],
            "quotes_count": quotes_count,
            "vendor_artifact_count": vendor_summary["vendor_count"],
            "vendor_artifact_has_vendors": vendor_summary["has_vendors"],
            "download_pdfs_ok": result["steps"]["download_pdfs"]["ok"],
            "file_count": file_summary["file_count"],
            "official_pdf_count": file_summary["official_pdf_count"],
            "snapshot_count": file_summary["snapshot_count"],
            "export_ok": result["steps"]["export_bid_package"]["ok"],
        }

        csv_rows.append({
            "opportunity_id": opp_id,
            "solicitation_number": sol,
            "title": opp["title"],
            "parse_ok": result["summary"]["parse_ok"],
            "checklist_ok": result["summary"]["checklist_ok"],
            "vendors_ok": result["summary"]["vendors_ok"],
            "email_ok": result["summary"]["email_ok"],
            "seed_quotes_ok": result["summary"]["seed_quotes_ok"],
            "quotes_count": result["summary"]["quotes_count"],
            "vendor_artifact_count": result["summary"]["vendor_artifact_count"],
            "vendor_artifact_has_vendors": result["summary"]["vendor_artifact_has_vendors"],
            "download_pdfs_ok": result["summary"]["download_pdfs_ok"],
            "file_count": result["summary"]["file_count"],
            "official_pdf_count": result["summary"]["official_pdf_count"],
            "snapshot_count": result["summary"]["snapshot_count"],
            "export_ok": result["summary"]["export_ok"],
        })

        full_results.append(result)

    json_path = OUT_DIR / "backend_smoke_test_results.json"
    csv_path = OUT_DIR / "backend_smoke_test_summary.csv"

    json_path.write_text(json.dumps(full_results, indent=2, default=str), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    print("")
    print("DONE")
    print(f"JSON report: {json_path.resolve()}")
    print(f"CSV summary: {csv_path.resolve()}")

    print("")
    print("Vendor shortlist failures / empties:")
    for row in csv_rows:
        if not row["vendors_ok"] or not row["vendor_artifact_has_vendors"]:
            print(f"- opp_id={row['opportunity_id']} | sol={row['solicitation_number']} | vendors_ok={row['vendors_ok']} | vendor_artifact_count={row['vendor_artifact_count']} | quotes_count={row['quotes_count']}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
