from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Entry:
    description: str
    amount: Decimal
    category: str = "misc"

    def __post_init__(self):
        if not self.description:
            raise ValueError("description is required")
        object.__setattr__(self, "amount", Decimal(str(self.amount)))
