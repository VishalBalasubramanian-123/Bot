from datetime import datetime
from qdrant_client import models

class FilterBuilder:
    def __init__(self):
        self.must: list[models.Condition] = []

    def error(self, value):
        raise ValueError(f"Value {value} is not an datetime string")

    def is_datetime_string(self, value: str) -> bool:
        """Return True if the given string can be parsed as an ISO 8601 datetime, False otherwise."""
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False

    def _build_lte_condition(self, key: str, value: str) -> models.Condition:
        if isinstance(value, str) and self.is_datetime_string(value):
            dt_value = datetime.fromisoformat(value)
            return models.FieldCondition(key=key, range=models.DatetimeRange(lte=dt_value))

        self.error(value)

    def _build_gte_condition(self, key: str, value: str) -> models.Condition:
        if isinstance(value, str) and self.is_datetime_string(value):
            dt_value = datetime.fromisoformat(value)
            return models.FieldCondition(key=key, range=models.DatetimeRange(gte=dt_value))

        self.error(value)

    def _build_in_condition(self, key: str, value: list[models.ValueVariants]) -> models.Condition:
        return models.FieldCondition(key=key, match=models.MatchAny(any=value))

    def add_senders(self, senders: list[str]) -> "FilterBuilder":
        if senders:
            self.must.append(self._build_in_condition("sender", senders))
        return self
    
    def add_participants(self, to: list[str]) -> "FilterBuilder":
        if to:
            self.must.append(self._build_in_condition("participants", to))
        return self
    
    def add_date_range(self, date_range: list[str], intent: str = "range") -> "FilterBuilder":
        if date_range:
            parsed = sorted(date_range)
            if intent == "range":
                self.must.append(self._build_gte_condition("date", parsed[0]))
                self.must.append(self._build_lte_condition("date", parsed[1]))
            elif intent == "gte":
                self.must.append(self._build_gte_condition("date", parsed[0]))
            else:
                self.must.append(self._build_lte_condition("date", parsed[0]))

        return self
    
    def add_labels(self, labels: list[str]) -> "FilterBuilder":
        if labels:
            self.must.append(self._build_in_condition("labels", labels))
        return self

    def add_source(self, source: list[str]) -> "FilterBuilder":
        if source:
            self.must.append(self._build_in_condition("source", source))
        return self

    def build(self) -> models.Filter | None:
        """Build the final filter from a list of conditions."""
        if not self.must:
            return None
        
        # Handles Single and Multiple conditions - combine with AND logic
        return models.Filter(must=self.must)