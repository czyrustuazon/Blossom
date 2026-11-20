from dataclasses import dataclass, field


@dataclass
class Item:
    sku: str
    name: str
    qty: int = 0
    unit_cost: float = 0.0
    tags: list = field(default_factory=list)

    @property
    def value(self) -> float:
        return round(self.qty * self.unit_cost, 2)

    def needs_restock(self, threshold: int = 5) -> bool:
        return self.qty < threshold
