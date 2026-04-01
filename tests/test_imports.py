from app.services.importers import (
    detect_statement_type,
    parse_ofx_bytes,
    parse_statement_bytes,
    parse_xml_bytes,
)


def test_imports_page_requires_auth(app_client):
    response = app_client.client.get("/imports", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


def test_imports_page_renders_for_logged_user(logged_client):
    response = logged_client.client.get("/imports")
    assert response.status_code == 200
    assert "Importar Extratos" in response.text
    assert "Bradesco" in response.text
    assert "Nubank" in response.text


def test_preview_import_csv_from_account_statement(logged_client):
    csv_content = (
        "Data;Descricao;Valor\n"
        "15/03/2026;Transferencia recebida;1500,55\n"
        "16/03/2026;Supermercado;-120,90\n"
    ).encode("utf-8")

    response = logged_client.client.post(
        "/api/imports/preview",
        files={"file": ("extrato_inter.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bank"] == "inter"
    assert payload["statement_type"] == "conta"
    assert payload["count"] == 2
    assert payload["items"][0]["description"] == "Transferencia recebida"


def test_preview_import_xml_card_with_bank_hint(logged_client):
    xml_content = b"""
    <fatura>
      <movimento>
        <data>2026-03-15</data>
        <descricao>Farmacia</descricao>
        <valor>-45.10</valor>
      </movimento>
      <movimento>
        <data>2026-03-16</data>
        <descricao>Mercado</descricao>
        <valor>-120.55</valor>
      </movimento>
    </fatura>
    """

    response = logged_client.client.post(
        "/api/imports/preview",
        files={"file": ("fatura_cartao.xml", xml_content, "application/xml")},
        data={"bank_hint": "nubank"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bank"] == "nubank"
    assert payload["statement_type"] == "cartao"
    assert payload["count"] == 2


def test_preview_import_rejects_unsupported_extension(logged_client):
    response = logged_client.client.post(
        "/api/imports/preview",
        files={"file": ("arquivo.txt", b"conteudo", "text/plain")},
    )

    assert response.status_code == 400
    assert "Formato nao suportado" in response.json()["detail"]


def test_parse_ofx_statement_extracts_movements():
    content = b"""
    <OFX>
      <BANKTRANLIST>
        <STMTTRN>
          <TRNAMT>-89.90
          <DTPOSTED>20260315
          <MEMO>Padaria
        </STMTTRN>
        <STMTTRN>
          <TRNAMT>2500.00
          <DTPOSTED>20260314
          <NAME>Salario
        </STMTTRN>
      </BANKTRANLIST>
    </OFX>
    """

    items = parse_ofx_bytes(content)

    assert len(items) == 2
    assert items[0]["kind"] == "debit"
    assert items[1]["kind"] == "credit"


def test_parse_xml_statement_extracts_movements():
    content = b"""
    <extrato>
      <movimento>
        <data>2026-03-15</data>
        <descricao>Pix recebido</descricao>
        <valor>450.00</valor>
      </movimento>
      <movimento>
        <data>2026-03-16</data>
        <descricao>Compra mercado</descricao>
        <valor>-120.00</valor>
      </movimento>
    </extrato>
    """

    items = parse_xml_bytes(content)

    assert len(items) == 2
    assert items[0]["description"] == "Pix recebido"
    assert items[1]["kind"] == "debit"


def test_parse_statement_accepts_cvs_alias():
    content = (
        "Data;Descricao;Valor\n"
        "15/03/2026;Recebimento;99,90\n"
    ).encode("utf-8")

    result = parse_statement_bytes("extrato.cvs", content)

    assert result["file_format"] == "cvs"
    assert result["count"] == 1


def test_detect_statement_type_identifies_card_language():
    result = detect_statement_type("Fatura do cartao com compras e limite", "arquivo.pdf")
    assert result == "cartao"
