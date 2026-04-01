from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


# ---- ENUMS -------------------------------------------------

class AccountType(str, Enum):
    checking   = "checking"
    savings    = "savings"
    wallet     = "wallet"
    investment = "investment"
    shared     = "shared"

class TransactionType(str, Enum):
    income   = "income"
    expense  = "expense"
    transfer = "transfer"

class PaymentMethod(str, Enum):
    account = "account"
    pix = "pix"
    card = "card"
    boleto = "boleto"
    cash = "cash"

class TransactionStatus(str, Enum):
    paid = "paid"
    pending = "pending"
    scheduled = "scheduled"
    cancelled = "cancelled"

class InvoiceStatus(str, Enum):
    open = "open"
    closed = "closed"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"

class TransactionScope(str, Enum):
    personal = "personal"
    shared   = "shared"

class RecurrenceFrequency(str, Enum):
    daily     = "daily"
    weekly    = "weekly"
    biweekly  = "biweekly"
    monthly   = "monthly"
    yearly    = "yearly"

class CardNetwork(str, Enum):
    visa      = "visa"
    mastercard= "mastercard"
    elo       = "elo"
    amex      = "amex"
    hipercard = "hipercard"
    other     = "other"

class GoalScope(str, Enum):
    personal = "personal"
    shared   = "shared"

class FamilyRole(str, Enum):
    owner  = "owner"
    member = "member"


# ---- AUTH --------------------------------------------------

class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres")
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PasswordReset(BaseModel):
    email: EmailStr


# ---- PROFILE -----------------------------------------------

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    currency: Optional[str] = "BRL"
    timezone: Optional[str] = "America/Sao_Paulo"


# ---- ACCOUNTS ----------------------------------------------

class AccountCreate(BaseModel):
    name: str
    type: AccountType = AccountType.checking
    bank_name: Optional[str] = None
    icon: Optional[str] = "🏦"
    color: Optional[str] = "#6c63ff"
    initial_balance: float = 0.0
    is_shared: bool = False
    family_group_id: Optional[str] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    bank_name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None
    include_in_total: Optional[bool] = None


# ---- CATEGORIES --------------------------------------------

class CategoryCreate(BaseModel):
    name: str
    slug: str
    icon: str = "📦"
    color: str = "#6c63ff"
    type: TransactionType
    parent_id: Optional[str] = None


# ---- TRANSACTIONS ------------------------------------------

class TransactionCreate(BaseModel):
    account_id: Optional[str] = None
    credit_card_id: Optional[str] = None
    card_id: Optional[str] = None
    invoice_id: Optional[str] = None
    category_id: str
    to_account_id: Optional[str] = None
    type: TransactionType
    scope: TransactionScope = TransactionScope.personal
    payment_method: PaymentMethod = PaymentMethod.account
    status: Optional[TransactionStatus] = None
    description: str
    amount: float
    date: date
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    tags: List[str] = []
    is_installment: bool = False
    total_installments: Optional[int] = None
    installment_total: Optional[int] = None
    installment_number: Optional[int] = None
    installment_group_id: Optional[str] = None
    family_group_id: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError("Valor deve ser positivo")
        return v

    @field_validator("installment_total")
    @classmethod
    def installment_total_valid(cls, v):
        if v is not None and v < 2:
            raise ValueError("Parcelamento deve ter pelo menos 2 parcelas")
        return v

class TransactionUpdate(BaseModel):
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    card_id: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    status: Optional[TransactionStatus] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[date] = None
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    scope: Optional[TransactionScope] = None
    is_confirmed: Optional[bool] = None

class TransactionFilters(BaseModel):
    type: Optional[TransactionType] = None
    scope: Optional[TransactionScope] = None
    account_id: Optional[str] = None
    credit_card_id: Optional[str] = None
    category_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    search: Optional[str] = None
    page: int = 1
    per_page: int = 30


# ---- CREDIT CARDS ------------------------------------------

class CreditCardCreate(BaseModel):
    name: str
    bank_name: Optional[str] = None
    brand: Optional[str] = None
    last_four: Optional[str] = None
    network: CardNetwork = CardNetwork.visa
    credit_limit: Optional[float] = None
    limit_amount: Optional[float] = None
    closing_day: int
    due_day: int
    account_id: Optional[str] = None
    color_start: str = "#1a1040"
    color_end: str = "#2d1b6e"
    is_shared: bool = False
    family_group_id: Optional[str] = None

    @field_validator("credit_limit", "limit_amount")
    @classmethod
    def valid_limit(cls, v):
        if v is not None and v < 0:
            raise ValueError("Limite deve ser maior ou igual a zero")
        return v

    @field_validator("closing_day", "due_day")
    @classmethod
    def valid_day(cls, v):
        if not 1 <= v <= 31:
            raise ValueError("Dia deve estar entre 1 e 31")
        return v


class InvoicePaymentCreate(BaseModel):
    invoice_id: str
    account_id: str
    amount: float
    payment_date: date
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def invoice_payment_amount_positive(cls, v):
        if v <= 0:
            raise ValueError("Valor deve ser positivo")
        return v


class BoletoSettlementCreate(BaseModel):
    account_id: str
    payment_date: date
    notes: Optional[str] = None


# ---- RECURRING ---------------------------------------------

class RecurringCreate(BaseModel):
    account_id: Optional[str] = None
    credit_card_id: Optional[str] = None
    category_id: str
    type: TransactionType
    scope: TransactionScope = TransactionScope.personal
    description: str
    amount: float
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    start_date: date
    end_date: Optional[date] = None
    day_of_month: Optional[int] = None
    family_group_id: Optional[str] = None


# ---- GOALS -------------------------------------------------

class GoalCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: str = "🎯"
    target_amount: float
    target_date: Optional[date] = None
    scope: GoalScope = GoalScope.personal
    color: str = "#6c63ff"
    linked_account_id: Optional[str] = None
    family_group_id: Optional[str] = None

    @field_validator("target_amount")
    @classmethod
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError("Valor alvo deve ser positivo")
        return v

class GoalContributionCreate(BaseModel):
    amount: float
    notes: Optional[str] = None
    date: date


# ---- FAMILY ------------------------------------------------

class FamilyGroupCreate(BaseModel):
    name: str

class FamilyJoin(BaseModel):
    invite_code: str


# ---- RESPONSES ---------------------------------------------

class PaginatedResponse(BaseModel):
    data: list
    count: int
    page: int
    per_page: int
    total_pages: int

class ApiResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None

class MonthlyKPIs(BaseModel):
    total_income: float
    total_expenses: float
    net_result: float
    consolidated_balance: float
    savings_rate: float
    month: str

class CategorySummary(BaseModel):
    category_name: str
    category_icon: str
    category_color: str
    total: float
    percentage: float
    count: int

class MonthlyEvolution(BaseModel):
    month: str
    income: float
    expenses: float
    net: float

class Insight(BaseModel):
    type: str  # warning | success | info
    icon: str
    title: str
    description: str
