from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RIDERS_JS = ROOT / "frontend-v2" / "fleet" / "views" / "riders.js"


def test_vehicle_collection_calls_do_not_trigger_https_redirects():
    source = RIDERS_JS.read_text(encoding="utf-8")
    assert "api.get('/vehicles/')" in source
    assert "api.post('/vehicles/'," in source
    assert "api.get('/vehicles')" not in source
    assert "api.post('/vehicles'," not in source


def test_rider_creation_requires_explicit_contract_branch():
    source = RIDERS_JS.read_text(encoding="utf-8")
    assert "اختر العقد وفرع التشغيل قبل إضافة السائق" in source
    assert "contract_branch_id: branchId ? parseInt(branchId) : 1" not in source
