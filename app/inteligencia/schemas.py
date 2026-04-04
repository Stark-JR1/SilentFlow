from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class IntelligenceSettingsPayload(BaseModel):
    enable_suggestions: bool = True
    enable_auto_fill: bool = False
    enable_recurrence_detection: bool = True
    learn_from_manual_edits: bool = True
    learn_from_imported_transactions: bool = Field(
        default=True,
        description="Stored for forward compatibility; imported-transaction learning is not wired in the backend yet.",
    )
    show_explanations: bool = True
    min_confidence_to_suggest: float = Field(default=0.60, ge=0, le=1)
    min_confidence_to_autofill: float = Field(default=0.90, ge=0, le=1)
    description_similarity_threshold: float = Field(default=0.50, ge=0, le=1)
    min_repetitions_for_pattern: int = Field(default=3, ge=1, le=50)


class SuggestionRequest(BaseModel):
    description: str
    amount: Optional[float] = None


class FeedbackRequest(BaseModel):
    transaction_id: Optional[str] = None
    input_description: str
    suggested_rule_id: Optional[str] = None
    suggested_category_id: Optional[str] = None
    chosen_category_id: Optional[str] = None
    suggested_account_id: Optional[str] = None
    chosen_account_id: Optional[str] = None
    suggested_card_id: Optional[str] = None
    chosen_card_id: Optional[str] = None
    suggested_type: Optional[str] = None
    chosen_type: Optional[str] = None
    accepted: bool = False
    confidence_at_time: Optional[float] = Field(default=None, ge=0, le=1)


class UserBehaviorProfileOut(BaseModel):
    avg_monthly_income: float = 0
    avg_monthly_expense: float = 0
    avg_monthly_savings: float = 0
    avg_transaction_value: float = 0
    recurring_transactions_count: int = 0
    active_months_count: int = 0
    top_category_id: Optional[str] = None
    top_category_name: Optional[str] = None
    top_category_share: float = 0


class IntelligenceAlertOut(BaseModel):
    id: str
    alert_type: str
    severity: str
    title: str
    message: str
    reference_date: Optional[str] = None
    reference_month: Optional[str] = None
    amount: Optional[float] = None
    is_read: bool = False
    is_dismissed: bool = False
    metadata: dict = Field(default_factory=dict)


class IntelligenceAlertsSummaryOut(BaseModel):
    total: int = 0
    unread: int = 0
    critical: int = 0
    items: list[IntelligenceAlertOut] = Field(default_factory=list)
