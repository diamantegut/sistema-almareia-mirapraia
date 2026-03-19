var currentGuestRoom = null;
var currentGuestReservationId = null;
var currentGuestContext = { source: 'rooms' };
var currentGuestPayload = null;

function openViewGuestModal(guestId, guestName, roomNum, context) {
    currentGuestRoom = roomNum;
    currentGuestReservationId = guestId;
    currentGuestContext = context || { source: 'rooms' };
    cancelGuestEdit();

    var modalEl = document.getElementById('viewGuestModal');
    var modal = new bootstrap.Modal(modalEl);

    document.getElementById('viewGuestLoading').classList.remove('d-none');
    document.getElementById('viewGuestContent').classList.add('d-none');
    document.getElementById('viewGuestError').classList.add('d-none');
    modal.show();

    if (!guestId || guestId === 'None') {
        showGuestError("ID do hóspede não encontrado. É um registro antigo?");
        return;
    }

    fetch('/api/guest/details?reservation_id=' + encodeURIComponent(guestId))
        .then(response => response.json().then(data => ({ status: response.status, body: data })))
        .then(({ status, body }) => {
            if (status >= 400 || !body.success) throw new Error((body && body.error) || "Erro ao carregar ficha do hóspede");
            populateGuestModal(body.data, roomNum, guestId, context || {});
        })
        .catch(err => {
            console.error(err);
            showGuestError(err.message);
        });
}

function parseListString(value) {
    if (Array.isArray(value)) return value;
    return String(value || '')
        .split(',')
        .map(x => x.trim())
        .filter(Boolean);
}

function populateGuestModal(responseData, roomNum, reservationId, context) {
    var guest = responseData.guest || {};
    var reservation = responseData.reservation || {};
    var personal = guest.personal_info || {};
    var fiscal = guest.fiscal_info || {};
    var history = guest.history || [];
    var operational = guest.operational_info || {};
    var contextData = context || {};
    currentGuestPayload = {
        reservationId: reservationId || reservation.id || '',
        personal: personal,
        fiscal: fiscal,
        operational: operational,
        reservation: reservation,
        context: contextData
    };

    setText('vg_name', personal.name || reservation.guest_name || 'Hóspede');
    setText('vg_ficha', personal.ficha_number || 'N/A');
    setText('vg_doc', personal.cpf || personal.doc_id || 'Não informado');
    setText('vg_birth', personal.birth_date || '-');
    setText('vg_email', personal.email || '-');
    setText('vg_phone', personal.phone || reservation.phone || '-');
    var addrStr = personal.address || '';
    if (personal.city) addrStr += (addrStr ? ', ' : '') + personal.city;
    if (personal.state) addrStr += (addrStr ? ' - ' : '') + personal.state;
    setText('vg_address', addrStr || 'Endereço não cadastrado');
    setText('vg_fiscal_doc', fiscal.cpf_cnpj || fiscal.cpf || fiscal.cnpj || '-');
    setText('vg_fiscal_name', fiscal.razao_social || fiscal.nome || '-');

    setText('vg_room', roomNum || responseData.current_room || reservation.room || '-');
    setText('vg_status', reservation.status || contextData.status || 'Hospedado');
    setText('vg_checkin', reservation.checkin || '-');
    setText('vg_checkout', reservation.checkout || '-');
    setText('vg_channel', reservation.channel || contextData.channel || '-');
    setText('vg_category', reservation.category || contextData.category || '-');
    setText('vg_reservation_id_hidden', reservationId || reservation.id || '');

    var stayFinancial = responseData.reservation_financial || {};
    var consFinancial = responseData.consumption_financial || {};
    setText('vg_stay_total', formatCurrency(parseFloat(stayFinancial.total || reservation.amount || 0)));
    setText('vg_stay_paid', formatCurrency(parseFloat(stayFinancial.paid || reservation.paid_amount || 0)));
    setText('vg_stay_balance', formatCurrency(parseFloat(stayFinancial.pending || reservation.to_receive || 0)));
    setText('vg_cons_total', formatCurrency(parseFloat(consFinancial.total || 0)));
    setText('vg_cons_paid', formatCurrency(parseFloat(consFinancial.paid || 0)));
    setText('vg_cons_balance', formatCurrency(parseFloat(consFinancial.pending || 0)));

    var dietary = operational.dietary_restrictions || [];
    var breakfastStart = operational.breakfast_time_start || '--:--';
    var breakfastEnd = operational.breakfast_time_end || '--:--';
    var commemorative = operational.commemorative_dates || [];
    setText('vg_allergies', operational.allergies || '-');
    setText('vg_dietary', dietary.length ? dietary.join(', ') : '-');
    setText('vg_breakfast', (operational.breakfast_time_start || operational.breakfast_time_end) ? `${breakfastStart} - ${breakfastEnd}` : '-');
    setText('vg_commemorative', commemorative.length ? commemorative.join(', ') : '-');
    setText('vg_vip', operational.vip_note || '-');

    var tbody = document.getElementById('vg_history_table');
    tbody.innerHTML = '';
    if (history && history.length > 0) {
        history.forEach(h => {
            var statusMap = { 'active': 'Hospedado', 'checked_out': 'Finalizado', 'cancelled': 'Cancelado' };
            var statusLabel = statusMap[h.status] || h.status || 'N/A';
            var tr = document.createElement('tr');
            tr.innerHTML = `<td>${h.checkin || '-'}</td><td>${h.room || '-'}</td><td>${formatCurrency(h.total || 0)}</td><td><span class="badge bg-secondary">${statusLabel}</span></td>`;
            tbody.appendChild(tr);
        });
    } else {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Nenhum histórico encontrado.</td></tr>';
    }

    var actionWrap = document.getElementById('vg_header_actions');
    var btnReceive = document.getElementById('vg_btn_receive_reservation');
    var btnTimeline = document.getElementById('vg_btn_fin_timeline');
    var btnCheckin = document.getElementById('vg_btn_open_checkin');
    var btnDetails = document.getElementById('vg_btn_consumption_details');
    if (actionWrap) actionWrap.classList.add('d-none');
    if (btnDetails) btnDetails.classList.remove('d-none');

    if ((contextData.source || 'rooms') === 'reservations') {
        if (actionWrap) actionWrap.classList.remove('d-none');
        if (btnDetails) btnDetails.classList.add('d-none');
        if (btnReceive) {
            btnReceive.onclick = function() {
                if (typeof openReservationPaymentModal === 'function') {
                    openReservationPaymentModal(reservationId || reservation.id, personal.name || reservation.guest_name || 'Hóspede', reservation.category || contextData.category || '-');
                }
            };
        }
        if (btnTimeline) {
            btnTimeline.onclick = function() {
                var legacyResInput = document.getElementById('guestResId');
                if (legacyResInput) legacyResInput.value = reservationId || reservation.id || '';
                if (typeof openFinancialTimelineFromModal === 'function') openFinancialTimelineFromModal();
            };
        }
        if (btnCheckin) {
            btnCheckin.onclick = function() {
                var rid = reservationId || reservation.id || '';
                if (rid) window.location.href = `/reception/rooms?open_checkin=true&reservation_id=${encodeURIComponent(rid)}`;
            };
        }
    }

    document.getElementById('viewGuestLoading').classList.add('d-none');
    document.getElementById('viewGuestContent').classList.remove('d-none');
}

function showGuestError(msg) {
    document.getElementById('viewGuestLoading').classList.add('d-none');
    document.getElementById('viewGuestError').classList.remove('d-none');
    document.getElementById('viewGuestErrorMsg').textContent = msg;
}

function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
}

function setInputValue(id, val) {
    var el = document.getElementById(id);
    if (el) el.value = val || '';
}

function formatCurrency(val) {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
}

function switchToEdit() {
    if (!currentGuestPayload || !currentGuestPayload.reservationId) return;
    var personal = currentGuestPayload.personal || {};
    var fiscal = currentGuestPayload.fiscal || {};
    var operational = currentGuestPayload.operational || {};

    setInputValue('vg_edit_name', personal.name || currentGuestPayload.reservation.guest_name || '');
    setInputValue('vg_edit_doc', personal.doc_id || personal.cpf || '');
    setInputValue('vg_edit_birth', personal.birth_date || '');
    setInputValue('vg_edit_email', personal.email || '');
    setInputValue('vg_edit_phone', personal.phone || '');
    setInputValue('vg_edit_address', personal.address || '');
    setInputValue('vg_edit_city', personal.city || '');
    setInputValue('vg_edit_state', personal.state || '');
    setInputValue('vg_edit_fiscal_doc', fiscal.cpf_cnpj || fiscal.cpf || fiscal.cnpj || '');
    setInputValue('vg_edit_fiscal_name', fiscal.razao_social || fiscal.nome || '');
    setInputValue('vg_edit_allergies', operational.allergies || '');
    setInputValue('vg_edit_dietary', parseListString(operational.dietary_restrictions).join(', '));
    setInputValue('vg_edit_breakfast_start', operational.breakfast_time_start || '');
    setInputValue('vg_edit_breakfast_end', operational.breakfast_time_end || '');
    setInputValue('vg_edit_commemorative', parseListString(operational.commemorative_dates).join(', '));
    setInputValue('vg_edit_vip', operational.vip_note || '');

    var panel = document.getElementById('vg_edit_panel');
    if (panel) panel.classList.remove('d-none');
}

function cancelGuestEdit() {
    var panel = document.getElementById('vg_edit_panel');
    if (panel) panel.classList.add('d-none');
}

function saveUnifiedGuestData() {
    if (!currentGuestPayload || !currentGuestPayload.reservationId) return;
    var saveBtn = document.getElementById('vg_save_btn');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Salvando...';
    }

    var personal = {
        name: document.getElementById('vg_edit_name').value.trim(),
        doc_id: document.getElementById('vg_edit_doc').value.trim(),
        birth_date: document.getElementById('vg_edit_birth').value.trim(),
        email: document.getElementById('vg_edit_email').value.trim(),
        phone: document.getElementById('vg_edit_phone').value.trim(),
        address: document.getElementById('vg_edit_address').value.trim(),
        city: document.getElementById('vg_edit_city').value.trim(),
        state: document.getElementById('vg_edit_state').value.trim()
    };
    var fiscalDoc = document.getElementById('vg_edit_fiscal_doc').value.trim();
    var fiscal = {
        cpf_cnpj: fiscalDoc,
        razao_social: document.getElementById('vg_edit_fiscal_name').value.trim()
    };
    var operational = {
        allergies: document.getElementById('vg_edit_allergies').value.trim(),
        dietary_restrictions: parseListString(document.getElementById('vg_edit_dietary').value),
        breakfast_time_start: document.getElementById('vg_edit_breakfast_start').value.trim(),
        breakfast_time_end: document.getElementById('vg_edit_breakfast_end').value.trim(),
        commemorative_dates: parseListString(document.getElementById('vg_edit_commemorative').value),
        vip_note: document.getElementById('vg_edit_vip').value.trim()
    };

    fetch('/api/guest/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            reservation_id: currentGuestPayload.reservationId,
            personal_info: personal,
            fiscal_info: fiscal,
            operational_info: operational
        })
    })
        .then(response => response.json().then(data => ({ status: response.status, body: data })))
        .then(({ status, body }) => {
            if (status >= 400 || !body.success) throw new Error((body && body.error) || 'Falha ao salvar ficha.');
            cancelGuestEdit();
            return fetch('/api/guest/details?reservation_id=' + encodeURIComponent(currentGuestPayload.reservationId));
        })
        .then(response => response.json().then(data => ({ status: response.status, body: data })))
        .then(({ status, body }) => {
            if (status >= 400 || !body.success) throw new Error((body && body.error) || 'Falha ao recarregar ficha.');
            populateGuestModal(body.data, currentGuestRoom, currentGuestPayload.reservationId, currentGuestContext || {});
            alert('Ficha atualizada com sucesso.');
        })
        .catch(err => alert(err.message))
        .finally(() => {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Salvar Ficha';
            }
        });
}

function viewDetailedCharges() {
    if ((currentGuestContext && currentGuestContext.source) === 'reservations') {
        alert("Detalhes da conta de consumo disponíveis na tela de quartos.");
        return;
    }
    var guestModalEl = document.getElementById('viewGuestModal');
    var guestModal = bootstrap.Modal.getInstance(guestModalEl);
    guestModal.hide();
    setTimeout(() => {
        var chargesModalEl = document.getElementById('roomChargesModal' + currentGuestRoom);
        if (chargesModalEl) {
            var chargesModal = new bootstrap.Modal(chargesModalEl);
            chargesModal.show();
        } else {
            alert("Detalhes da conta não disponíveis nesta tela.");
        }
    }, 500);
}
