from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AddonFacts:
    signal_confirmed: bool
    profit_multiple: Decimal | None
    score: Decimal | None
    entry_score: Decimal | None
    stop_risk: Decimal | None
    proposed_stop_risk: Decimal | None
    constraint_allowed: bool
    planned_quantity: int
    already_added: bool


def addon_quantity(facts: AddonFacts) -> int:
    if facts.already_added or not facts.signal_confirmed or not facts.constraint_allowed:
        return 0
    if facts.profit_multiple is None or facts.profit_multiple < Decimal("1"):
        return 0
    if facts.score is None or facts.entry_score is None or facts.score < facts.entry_score:
        return 0
    if (
        facts.stop_risk is None
        or facts.proposed_stop_risk is None
        or facts.proposed_stop_risk > facts.stop_risk
    ):
        return 0
    return max(0, facts.planned_quantity)
