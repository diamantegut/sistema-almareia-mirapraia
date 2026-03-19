def test_consumption_modal_hides_technical_charge_id_and_raw_status():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Pedido #${escapeHtml(c.id)} · ${escapeHtml(c.status)}" not in html
    assert "Lançamento de consumo · ${escapeHtml(statusLabel(c.status))}" in html


def test_consumption_modal_payment_list_shows_method_and_amount():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "p.method_name || p.name || 'Forma não informada'" in html
    assert "isCashPayment(methodId, methodName)" in html
    assert "Pagamento acima do total só é permitido quando houver forma em dinheiro (troco)." in html


def test_consumption_modal_action_buttons_are_smaller():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert 'class="btn btn-sm btn-success"' in html
    assert 'class="btn btn-sm btn-outline-dark"' in html
    assert 'class="btn btn-sm btn-outline-primary"' in html
    assert 'class="btn btn-sm btn-primary" onclick="submitCloseRoomAccount()"' in html


def test_consumption_occurrence_shows_collaborator_with_fallback():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "function resolveOccurrenceCollaborator(charge, item)" in html
    assert "occ.collaborator || 'Não informado'" in html
    assert "Ocorrência: ${escapeHtml(occ.date)} · ${escapeHtml(occ.collaborator || 'Não informado')} · ${escapeHtml(statusLabel(occ.status))} · ${occ.qty}x" in html


def test_consumption_occurrence_collaborator_supports_multiple_origins():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "item && item.added_by" in html
    assert "item && item.batch_user" in html
    assert "charge && charge.waiter" in html
    assert "charge && charge.opened_by" in html


def test_rooms_template_has_upcoming_checkin_and_daily_payment_badges():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Próximo Check-in" in html
    assert "Diária pendente" in html
    assert "Diária (Reserva)" in html


def test_checkin_modal_has_pending_daily_decision_controls():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "checkinReservationBillingAlert" in html
    assert 'name="reservation_payment_decision"' in html
    assert 'value="defer_one_day"' in html
    assert "openReservationPaymentFromCheckin" in html
