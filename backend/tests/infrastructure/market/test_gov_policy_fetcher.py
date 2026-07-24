from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.infrastructure.market.gov_policy_fetcher import GovPolicyFetcher
from backend.app.infrastructure.market.official_evidence import OfficialEvidenceStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 24, 10, 0, tzinfo=SHANGHAI)


def test_fetcher_imports_fifteenth_five_year_plan_from_official_gov_page() -> None:
    html = """<html><head><meta name="others" content="2026-03-13 21:44"/></head>
    <body><h1 id="ti">中华人民共和国国民经济和社会发展第十五个五年规划纲要</h1>
    <div id="UCAP-CONTENT">规划正文</div></body></html>"""
    store = OfficialEvidenceStore.in_memory()
    fetcher = GovPolicyFetcher(store, get=lambda url: html, now=lambda: AS_OF)

    fetcher.refresh(security_ids=("000568.SZ", "601899.SH"), as_of_time=AS_OF)

    documents = store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",))
    assert len(documents) == 1
    assert documents[0].issuer == "中国政府网"
    assert documents[0].title.endswith("十五个五年规划纲要")
