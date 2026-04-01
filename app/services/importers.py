from __future__ import annotations

import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader


SUPPORTED_BANKS = ["bradesco", "c6 bank", "sicoob", "inter", "nubank"]
SUPPORTED_FORMATS = [".csv", ".cvs", ".ofx", ".xml", ".pdf"]


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _norm(value: str) -> str:
    value = _strip_accents(value or "").lower().strip()
    return re.sub(r"\s+", " ", value)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(value))


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    formats = (
        ("%Y-%m-%d", 10),
        ("%d/%m/%Y", 10),
        ("%d-%m-%Y", 10),
        ("%Y%m%d", 8),
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d%H%M%S.%f", len(value)),
    )
    for fmt, size in formats:
        try:
            return datetime.strptime(value[:size], fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{2}/\d{2}/\d{4})", value)
    if match:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
    return None


def _parse_amount(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip().replace("R$", "").replace(" ", "")
    if not raw:
        return None
    if raw.count(",") == 1 and raw.count(".") >= 1:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1 and raw.count(".") == 0:
        raw = raw.replace(",", ".")
    try:
        return float(Decimal(raw))
    except InvalidOperation:
        return None


def detect_bank(filename: str, text: str, bank_hint: str | None = None) -> str:
    if bank_hint:
        return bank_hint
    haystack = f"{filename} {text[:3000]}"
    normalized = _norm(haystack)
    if "bradesco" in normalized:
        return "bradesco"
    if "c6 bank" in normalized or re.search(r"\bc6\b", normalized):
        return "c6 bank"
    if "sicoob" in normalized:
        return "sicoob"
    if "inter" in normalized or "banco inter" in normalized:
        return "inter"
    if "nubank" in normalized or "nu pagamentos" in normalized:
        return "nubank"
    return "desconhecido"


def detect_statement_type(text: str, filename: str) -> str:
    normalized = _norm(f"{filename} {text[:3000]}")
    card_terms = [
        "fatura",
        "cartao",
        "creditcard",
        "credito",
        "compras",
        "limite",
    ]
    if any(term in normalized for term in card_terms):
        return "cartao"
    return "conta"


def _build_item(date_value: str | None, description: str | None, amount: float | None, source: str) -> dict | None:
    if not date_value or not description or amount is None:
        return None
    return {
        "date": date_value,
        "description": description.strip(),
        "amount": round(amount, 2),
        "kind": "credit" if amount >= 0 else "debit",
        "source": source,
    }


def parse_csv_bytes(content: bytes) -> list[dict]:
    decoded = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("Nao foi possivel ler o CSV.")

    sample = decoded[:1024]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"

    reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
    items: list[dict] = []
    for row in reader:
        lowered = {_compact(k): (v or "") for k, v in row.items() if k}
        date_value = None
        description = None
        amount = None

        for key in ("data", "date", "datalancamento", "dtlancamento", "dtmovimento"):
            if key in lowered:
                date_value = _parse_date(lowered[key])
                if date_value:
                    break

        for key in ("descricao", "historico", "titulo", "title", "memo", "estabelecimento", "lancamento"):
            if key in lowered and lowered[key].strip():
                description = lowered[key]
                break

        for key in ("valor", "amount", "valorfinal", "valortotal", "valororiginal"):
            if key in lowered:
                amount = _parse_amount(lowered[key])
                if amount is not None:
                    break

        if amount is None:
            credit = None
            debit = None
            for key in ("credito", "credit", "entrada"):
                if key in lowered:
                    credit = _parse_amount(lowered[key])
            for key in ("debito", "debit", "saida"):
                if key in lowered:
                    debit = _parse_amount(lowered[key])
            if credit is not None:
                amount = abs(credit)
            elif debit is not None:
                amount = -abs(debit)

        item = _build_item(date_value, description, amount, "csv")
        if item:
            items.append(item)
    return items


def parse_ofx_bytes(content: bytes) -> list[dict]:
    text = content.decode("utf-8", errors="ignore")
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, flags=re.S | re.I)
    items: list[dict] = []
    for block in blocks:
        amount_match = re.search(r"<TRNAMT>([^<\r\n]+)", block, flags=re.I)
        date_match = re.search(r"<DTPOSTED>([^<\r\n]+)", block, flags=re.I)
        memo_match = re.search(r"<MEMO>([^<\r\n]+)", block, flags=re.I)
        name_match = re.search(r"<NAME>([^<\r\n]+)", block, flags=re.I)

        amount = _parse_amount(amount_match.group(1)) if amount_match else None
        date_value = _parse_date(date_match.group(1)) if date_match else None
        description = memo_match.group(1).strip() if memo_match else (name_match.group(1).strip() if name_match else None)

        item = _build_item(date_value, description, amount, "ofx")
        if item:
            items.append(item)
    return items


def parse_xml_bytes(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    items: list[dict] = []
    candidates = [node for node in root.iter() if len(list(node)) >= 2]
    for node in candidates:
        children = {_compact(child.tag.split("}")[-1]): (child.text or "").strip() for child in list(node)}
        date_value = None
        description = None
        amount = None

        for key in ("data", "date", "datalancamento", "dtmovimento", "dtpost"):
            if key in children:
                date_value = _parse_date(children[key])
                if date_value:
                    break

        for key in ("descricao", "historico", "memo", "title", "titulo", "estabelecimento", "descricaoabreviada"):
            if key in children and children[key]:
                description = children[key]
                break

        for key in ("valor", "amount", "trnamt", "valorfinal", "valororiginal"):
            if key in children:
                amount = _parse_amount(children[key])
                if amount is not None:
                    break

        item = _build_item(date_value, description, amount, "xml")
        if item:
            items.append(item)
    return items


def parse_pdf_text(text: str) -> list[dict]:
    items: list[dict] = []
    date_pattern = r"(?P<date>\d{2}/\d{2}/\d{4})"
    amount_pattern = r"(?P<amount>-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        match = re.search(date_pattern, line)
        amount_matches = list(re.finditer(amount_pattern, line))
        if not match or not amount_matches:
            continue

        amount_match = amount_matches[-1]
        date_value = _parse_date(match.group("date"))
        amount = _parse_amount(amount_match.group("amount"))
        description = line[match.end() : amount_match.start()].strip(" -:|")

        item = _build_item(date_value, description, amount, "pdf")
        if item:
            items.append(item)
    return items


def parse_pdf_bytes(content: bytes) -> list[dict]:
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_pdf_text(text)


def parse_statement_bytes(filename: str, content: bytes, bank_hint: str | None = None) -> dict:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_FORMATS:
        raise ValueError("Formato nao suportado. Envie CSV, OFX, XML ou PDF.")

    if extension in {".csv", ".cvs"}:
        items = parse_csv_bytes(content)
        text = content.decode("latin-1", errors="ignore")
    elif extension == ".ofx":
        items = parse_ofx_bytes(content)
        text = content.decode("latin-1", errors="ignore")
    elif extension == ".xml":
        items = parse_xml_bytes(content)
        text = content.decode("utf-8", errors="ignore")
    else:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        items = parse_pdf_text(text)

    bank = detect_bank(filename, text, bank_hint)
    statement_type = detect_statement_type(text, filename)
    warnings: list[str] = []

    if not items:
        warnings.append(
            "Nenhuma movimentacao foi reconhecida automaticamente. Verifique o arquivo ou ajuste o parser para esse layout."
        )

    return {
        "filename": filename,
        "bank": bank,
        "statement_type": statement_type,
        "file_format": extension.lstrip("."),
        "count": len(items),
        "items": items[:500],
        "warnings": warnings,
    }
