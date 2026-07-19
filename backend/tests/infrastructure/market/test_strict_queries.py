from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.market.strict_queries import (
    StrictDataMissingError,
    TemporalDisclosureQueries,
    TemporalSecurityQueries,
)
from backend.app.infrastructure.persistence.strict_pit_rows import (
    FinancialDisclosureRow,
    FinancialFactRow,
    IndustryMembershipHistoryRow,
    PolicyDocumentRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
)


AS_OF = datetime(2020, 6, 1, 15, 30, tzinfo=UTC)
STRICT_QUERY_TABLES = (
    SecurityMasterHistoryRow.__table__,
    SecurityStatusDailyRow.__table__,
    IndustryMembershipHistoryRow.__table__,
    FinancialDisclosureRow.__table__,
    FinancialFactRow.__table__,
    PolicyDocumentRow.__table__,
)


@pytest.fixture
def strict_query_session(postgres_engine: Engine) -> Iterator[Session]:
    for table in STRICT_QUERY_TABLES:
        table.create(postgres_engine, checkfirst=True)
    _truncate_tables(postgres_engine)
    session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _truncate_tables(postgres_engine)


@pytest.mark.postgres
def test_universe_uses_available_listing_and_validity_intervals(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            master(
                "past",
                "PAST.SZ",
                listed_on=date(2010, 1, 1),
                delisted_on=date(2021, 1, 1),
            ),
            master("future-listing", "FUTURE.SZ", listed_on=date(2021, 1, 1)),
            master(
                "future-available",
                "FUTURE_DATA.SZ",
                available_at=datetime(2020, 6, 2, tzinfo=UTC),
            ),
            master("expired", "EXPIRED.SZ", valid_to=date(2020, 6, 1)),
        ]
    )
    strict_query_session.commit()

    assert TemporalSecurityQueries(strict_query_session).universe(AS_OF) == ("PAST.SZ",)


@pytest.mark.postgres
def test_universe_does_not_resurrect_an_invalidated_source_record(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            master("active", "PAST.SZ", source_record_id="master-PAST"),
            master(
                "invalidated",
                "PAST.SZ",
                source_record_id="master-PAST",
                valid_to=AS_OF.date(),
                available_at=AS_OF,
            ),
        ]
    )
    strict_query_session.commit()

    assert TemporalSecurityQueries(strict_query_session).universe(AS_OF) == ()


@pytest.mark.postgres
def test_status_and_industry_select_latest_available_deterministic_version(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            status("status-a", is_st=True, board="old", price_limit_pct=Decimal("0.05")),
            status("status-z", is_st=False, board="main", price_limit_pct=Decimal("0.10")),
            status("status-future", is_st=True, available_at=datetime(2020, 6, 2, tzinfo=UTC)),
            industry("industry-a", "OLD_A"),
            industry("industry-z", "OLD_Z"),
            industry("industry-future", "FUTURE", available_at=datetime(2020, 6, 2, tzinfo=UTC)),
        ]
    )
    strict_query_session.commit()
    queries = TemporalSecurityQueries(strict_query_session)

    selected_status = queries.status("PAST.SZ", AS_OF)
    assert selected_status.is_st is False
    assert selected_status.is_suspended is False
    assert selected_status.board == "main"
    assert selected_status.price_limit_pct == Decimal("0.10")
    assert queries.industry("PAST.SZ", AS_OF) == "OLD_Z"


@pytest.mark.postgres
def test_industry_does_not_resurrect_an_invalidated_source_record(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            industry("active", "OLD", source_record_id="industry-PAST"),
            industry(
                "invalidated",
                "REMOVED",
                source_record_id="industry-PAST",
                effective_to=AS_OF.date(),
                available_at=AS_OF,
            ),
        ]
    )
    strict_query_session.commit()

    with pytest.raises(StrictDataMissingError, match="industry missing: PAST.SZ"):
        TemporalSecurityQueries(strict_query_session).industry("PAST.SZ", AS_OF)


@pytest.mark.postgres
def test_financial_revision_and_facts_respect_available_cutoff_and_ties(
    strict_query_session: Session,
) -> None:
    first = disclosure("disclosure-1", "d-1", revision=1)
    future = disclosure(
        "disclosure-2",
        "d-2",
        revision=2,
        available_at=datetime(2020, 7, 1, tzinfo=UTC),
    )
    strict_query_session.add_all(
        [
            first,
            future,
            fact("fact-a", first.id, "f-a", "100"),
            fact("fact-z", first.id, "f-z", "101"),
        ]
    )
    strict_query_session.commit()

    selected = TemporalDisclosureQueries(strict_query_session).latest_financial("PAST.SZ", AS_OF)
    assert selected.disclosure_id == "d-1"
    assert selected.revision == 1
    assert selected.facts == {"revenue": "101"}


@pytest.mark.postgres
def test_policies_apply_availability_evidence_and_deterministic_ties(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            policy("official", "OFFICIAL_A", "A"),
            policy("traceable", "TRACEABLE_B", "B", official_parent_id="OFFICIAL_A"),
            policy("untraceable", "UNTRACEABLE_B", "B"),
            policy("future", "FUTURE", "A", first_observed_at=datetime(2020, 6, 2, tzinfo=UTC)),
            policy("tie-a", "TIE", "B"),
            policy("tie-z", "TIE", "A"),
        ]
    )
    strict_query_session.commit()

    documents = TemporalDisclosureQueries(strict_query_session).policies(AS_OF)
    by_id = {document.document_id: document for document in documents}
    assert set(by_id) == {"OFFICIAL_A", "TIE", "TRACEABLE_B", "UNTRACEABLE_B"}
    assert {document.document_id for document in documents if document.scoreable} == {
        "OFFICIAL_A",
        "TIE",
        "TRACEABLE_B",
    }


@pytest.mark.postgres
def test_policies_do_not_score_b_evidence_with_b_or_c_parent(
    strict_query_session: Session,
) -> None:
    strict_query_session.add_all(
        [
            policy("b-parent", "B_PARENT", "B"),
            policy("b-child", "B_CHILD", "B", official_parent_id="B_PARENT"),
            policy("c-parent", "C_PARENT", "C"),
            policy("c-child", "C_CHILD", "B", official_parent_id="C_PARENT"),
        ]
    )
    strict_query_session.commit()

    documents = TemporalDisclosureQueries(strict_query_session).policies(AS_OF)
    by_id = {document.document_id: document for document in documents}

    assert not by_id["B_CHILD"].scoreable
    assert not by_id["C_CHILD"].scoreable


def master(
    row_id: str,
    security_id: str,
    *,
    source_record_id: str | None = None,
    listed_on: date = date(2010, 1, 1),
    delisted_on: date | None = None,
    valid_to: date | None = None,
    available_at: datetime = datetime(2020, 1, 1, tzinfo=UTC),
) -> SecurityMasterHistoryRow:
    return SecurityMasterHistoryRow(
        id=row_id,
        source_record_id=source_record_id or row_id,
        security_id=security_id,
        name=security_id,
        listed_on=listed_on,
        delisted_on=delisted_on,
        valid_from=date(2010, 1, 1),
        valid_to=valid_to,
        available_at=available_at,
        source_artifact_hash=f"hash-{row_id}",
    )


def status(
    row_id: str,
    *,
    is_st: bool,
    board: str = "main",
    price_limit_pct: Decimal = Decimal("0.10"),
    available_at: datetime = AS_OF,
) -> SecurityStatusDailyRow:
    return SecurityStatusDailyRow(
        id=row_id,
        source_record_id=row_id,
        security_id="PAST.SZ",
        trade_date=AS_OF.date(),
        is_st=is_st,
        is_suspended=False,
        board=board,
        price_limit_pct=price_limit_pct,
        available_at=available_at,
        source_artifact_hash=f"hash-{row_id}",
    )


def industry(
    row_id: str,
    industry_id: str,
    *,
    source_record_id: str | None = None,
    effective_to: date | None = None,
    available_at: datetime = AS_OF,
) -> IndustryMembershipHistoryRow:
    return IndustryMembershipHistoryRow(
        id=row_id,
        source_record_id=source_record_id or row_id,
        security_id="PAST.SZ",
        available_at=available_at,
        source_artifact_hash=f"hash-{row_id}",
        payload_json=json.dumps(
            {
                "industry_id": industry_id,
                "effective_from": "2020-01-01",
                "effective_to": effective_to.isoformat() if effective_to else "",
            }
        ),
    )


def disclosure(
    row_id: str, source_record_id: str, *, revision: int, available_at: datetime = AS_OF
) -> FinancialDisclosureRow:
    return FinancialDisclosureRow(
        id=row_id,
        source_record_id=source_record_id,
        security_id="PAST.SZ",
        report_period=date(2020, 3, 31),
        revision=revision,
        published_at=available_at,
        available_at=available_at,
        source_artifact_hash=f"hash-{row_id}",
    )


def fact(row_id: str, disclosure_id: str, source_record_id: str, value: str) -> FinancialFactRow:
    return FinancialFactRow(
        id=row_id,
        source_record_id=source_record_id,
        disclosure_id=disclosure_id,
        disclosure_source_record_id="d-1",
        metric="revenue",
        value=value,
        unit="CNY",
        available_at=AS_OF,
        source_artifact_hash=f"hash-{row_id}",
    )


def policy(
    row_id: str,
    source_record_id: str,
    evidence_grade: str,
    *,
    official_parent_id: str | None = None,
    first_observed_at: datetime = AS_OF,
) -> PolicyDocumentRow:
    return PolicyDocumentRow(
        id=row_id,
        source_record_id=source_record_id,
        published_at=datetime(2020, 5, 1, tzinfo=UTC),
        first_observed_at=first_observed_at,
        available_at=max(datetime(2020, 5, 1, tzinfo=UTC), first_observed_at),
        evidence_grade=evidence_grade,
        official_parent_id=official_parent_id,
        content_hash=f"content-{row_id}",
        source_artifact_hash=f"hash-{row_id}",
    )


def _truncate_tables(engine: Engine) -> None:
    table_names = ", ".join(table.name for table in STRICT_QUERY_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
