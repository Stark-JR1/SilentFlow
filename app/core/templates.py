from fastapi.templating import Jinja2Templates

from app.utils.helpers import (
    ACCOUNT_TYPE_LABELS,
    FREQUENCY_LABELS,
    fmt_currency,
    format_date_br,
)


def build_templates(directory: str = "templates") -> Jinja2Templates:
    templates = Jinja2Templates(directory=directory)
    templates.env.filters["currency"] = fmt_currency
    templates.env.filters["date_br"] = format_date_br
    templates.env.globals["freq_labels"] = FREQUENCY_LABELS
    templates.env.globals["acc_labels"] = ACCOUNT_TYPE_LABELS
    return templates
