def test_guest_unified_modal_has_max_four_tabs():
    with open("app/templates/partials/guest_unified_modal.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert html.count('data-bs-target="#tab-') == 4
    assert "Resumo / Estadia" in html
    assert "Financeiro" in html
    assert "Dados do Hóspede" in html
    assert "Operacional" in html


def test_rooms_and_reservations_use_same_unified_modal_partial():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        rooms_html = f.read()
    with open("app/templates/reception_reservations.html", "r", encoding="utf-8") as f:
        reservations_html = f.read()
    assert "{% include 'partials/guest_unified_modal.html' %}" in rooms_html
    assert "{% include 'partials/guest_unified_modal.html' %}" in reservations_html


def test_reservations_delegates_open_to_unified_guest_modal():
    with open("app/templates/reception_reservations.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "if (typeof openViewGuestModal === 'function')" in html
    assert "openViewGuestModal(id, guest, '', {" in html
    assert "source: 'reservations'" in html


def test_both_screens_use_same_guest_view_js_endpoint():
    with open("app/static/js/guest_view.js", "r", encoding="utf-8") as f:
        js = f.read()
    with open("app/templates/reception_reservations.html", "r", encoding="utf-8") as f:
        res_html = f.read()
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        rooms_html = f.read()
    assert "fetch('/api/guest/details?reservation_id='" in js
    assert "guest_view.js" in res_html
    assert "guest_view.js" in rooms_html


def test_unified_financial_separation_is_present():
    with open("app/templates/partials/guest_unified_modal.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Hospedagem / Diárias (Caixa Reservas - NFS-e)" in html
    assert "Consumo (Caixa Recepção - NFC-e)" in html
