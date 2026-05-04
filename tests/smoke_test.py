#!/usr/bin/env python3
"""Offline smoke checks for the job application assistant."""

import ast
import json
import py_compile
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def check_py_compile():
    targets = list(SCRIPTS.glob("*.py")) + [ROOT / "edgar_formd_scraper.py"]
    for path in targets:
        py_compile.compile(str(path), doraise=True)


def check_config():
    cfg = json.loads((SCRIPTS / "scout_config.json").read_text())
    assert cfg["title_patterns_positive"], "missing positive title patterns"
    assert cfg["title_patterns_negative"], "missing negative title patterns"
    assert "scout_settings" in cfg, "missing scout_settings"


def check_companies_literal():
    source = (SCRIPTS / "ats_scout.py").read_text()
    tree = ast.parse(source)
    companies = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "COMPANIES":
                    companies = ast.literal_eval(node.value)
                    break
    assert isinstance(companies, list) and companies, "COMPANIES must be a non-empty list literal"
    required = {"name", "ats", "slug", "stage", "vertical"}
    for i, company in enumerate(companies):
        missing = required - set(company)
        assert not missing, f"company #{i} missing fields: {sorted(missing)}"


def check_dashboard_safety():
    sys.path.insert(0, str(SCRIPTS))
    import dashboard

    assert dashboard._tailored_path("../README.md", {".txt"}) is None
    assert dashboard._tailored_path("/etc/passwd", {".txt"}) is None

    app = dashboard.app
    app.testing = True
    client = app.test_client()

    resp = client.get("/api/tailored_resume_content?file=../README.md")
    assert resp.status_code == 400

    resp = client.post("/api/bash", json={"command": "pwd"})
    assert resp.status_code == 403

    resp = client.get("/api/companies")
    assert resp.status_code == 200

    resp = client.get("/api/data")
    assert resp.status_code == 200


def check_sqlite_migration():
    sys.path.insert(0, str(SCRIPTS))
    import migrate_to_db
    import storage

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobapp-smoke.db"
        counts = migrate_to_db.run(db_path, reset=True)
        conn = storage.connect(db_path)
        try:
            scout_companies = storage.load_scout_companies(conn)
            storage.add_dashboard_company(
                conn,
                name="Smoke Test Co",
                provider="ashby",
                slug="smoke-test-co",
                stage="Unknown",
                vertical="SaaS",
            )
            assert storage.get_ats_endpoint(conn, "ashby", "smoke-test-co") is not None
            assert storage.deactivate_company_by_name(conn, "Smoke Test Co")
            endpoint = storage.get_ats_endpoint(conn, "ashby", "smoke-test-co")
            assert endpoint["status"] == "deleted"

            alias = conn.execute("SELECT url FROM job_url_aliases LIMIT 1").fetchone()["url"]
            job_id = storage.update_job_interaction(
                conn,
                alias,
                selected=True,
                reviewed=True,
                comment="smoke",
                tags=["test"],
                manual_score=3,
                manual_score_comment="ok",
            )
            assert job_id is not None
            state = storage.export_dashboard_state(conn)
            assert state["selected"]
            assert state["comments"]
            assert state["feedback"]
        finally:
            conn.close()

    assert counts["companies"] >= counts["companies_seed"]
    assert counts["job_postings"] >= counts["raw_jobs_json"]
    assert counts["job_scores"] >= counts["shortlist_json"]
    assert len(scout_companies) >= counts["companies_seed"]
    assert all({"name", "ats", "slug", "stage", "vertical"} <= set(c) for c in scout_companies)


def main():
    checks = [
        check_py_compile,
        check_config,
        check_companies_literal,
        check_dashboard_safety,
        check_sqlite_migration,
    ]
    for check in checks:
        check()
        print(f"ok - {check.__name__}")
    print("smoke tests passed")


if __name__ == "__main__":
    main()
