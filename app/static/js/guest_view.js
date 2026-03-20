var currentGuestRoom = null;
var currentGuestReservationId = null;
var currentGuestContext = { source: 'rooms' };
var currentGuestPayload = null;
var currentCompanionDraft = [];
var dietaryPresetOptions = ['Sem Glúten', 'Sem Lactose', 'Vegano', 'Vegetariano', 'Low Carb', 'Sem Açúcar', 'Sem Frutos do Mar', 'Kosher', 'Halal'];
var allergyPresetOptions = ['Leite', 'Ovo', 'Glúten', 'Amendoim', 'Castanhas', 'Frutos do Mar', 'Soja', 'Morango', 'Corantes'];
var fruitPresetOptions = ['Mamão', 'Melão', 'Abacaxi', 'Banana', 'Maçã', 'Manga', 'Uva', 'Melancia', 'Kiwi'];

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
    if (typeof value === 'boolean' || value === null || value === undefined) return [];
    return String(value || '')
        .split(',')
        .map(x => x.trim())
        .filter(Boolean);
}

function parseBoolean(value) {
    if (typeof value === 'boolean') return value;
    var normalized = String(value || '').trim().toLowerCase();
    return ['1', 'true', 'sim', 'yes', 'y'].includes(normalized);
}

function normalizeText(value, maxLen) {
    return String(value || '').trim().slice(0, maxLen || 180);
}

function isValidHHMM(value) {
    if (!value) return true;
    return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(String(value).trim());
}

function sanitizeCompanion(companion, index) {
    var source = companion && typeof companion === 'object' ? companion : {};
    return {
        id: String(source.id || ('temp-' + index + '-' + Date.now())),
        name: String(source.name || source.full_name || '').trim(),
        relationship: String(source.relationship || '').trim(),
        doc_id: String(source.doc_id || source.cpf || '').trim(),
        phone: String(source.phone || '').trim(),
        email: String(source.email || '').trim(),
        dietary_restrictions: parseListString(source.dietary_restrictions),
        allergies: parseListString(source.allergies || source.allergies_list),
        food_notes: String(source.food_notes || '').trim(),
        breakfast_time: String(source.breakfast_time || '').trim(),
        breakfast_fruits: parseListString(source.breakfast_fruits || source.breakfast_fruit_preferences),
        breakfast_notes: String(source.breakfast_notes || '').trim(),
        is_birthday: parseBoolean(source.is_birthday),
        special_celebration: String(source.special_celebration || '').trim(),
        hospitality_notes: String(source.hospitality_notes || '').trim()
    };
}

function renderBadgeList(list, className) {
    var items = parseListString(list);
    if (!items.length) return '-';
    return items.map(function(item) { return '<span class="badge ' + className + ' me-1 mb-1">' + item + '</span>'; }).join('');
}

function renderHospitalityBadges(operational, companions) {
    var wrap = document.getElementById('vg_hospitality_badges');
    if (!wrap) return;
    var badges = [];
    if (parseBoolean(operational.is_birthday || operational.birthday_flag)) badges.push('<span class="badge bg-warning text-dark">Aniversariante</span>');
    if (String(operational.special_celebration || '').trim()) badges.push('<span class="badge bg-primary">Comemoração</span>');
    if (String(operational.vip_note || '').trim()) badges.push('<span class="badge bg-dark">VIP</span>');
    if (companions.some(function(c) { return parseBoolean(c.is_birthday); })) badges.push('<span class="badge bg-info text-dark">Acompanhante aniversariante</span>');
    wrap.innerHTML = badges.length ? badges.join(' ') : '<span class="text-muted small">Sem sinalização</span>';
}

function renderGuestList(personal, companions) {
    var tbody = document.getElementById('vg_guest_list');
    if (!tbody) return;
    var principalName = String(personal.name || '').trim() || 'Hóspede principal';
    var principalDoc = String(personal.doc_id || personal.cpf || '').trim() || '-';
    var principalPrefs = [];
    var op = (currentGuestPayload && currentGuestPayload.operational) || {};
    var principalDiet = parseListString(op.dietary_restrictions);
    var principalAllergies = parseListString(op.allergies || op.allergies_list);
    if (principalDiet.length) principalPrefs.push('Restrições: ' + principalDiet.join(', '));
    if (principalAllergies.length) principalPrefs.push('Alergias: ' + principalAllergies.join(', '));
    var rows = [];
    rows.push('<tr><td><strong>' + principalName + '</strong></td><td><span class="badge bg-primary-subtle text-primary-emphasis">Titular</span></td><td>' + principalDoc + '</td><td class="d-none d-md-table-cell">' + (principalPrefs.length ? principalPrefs.join(' · ') : '<span class="text-muted">Sem sinalizações</span>') + '</td></tr>');
    companions.forEach(function(c) {
        var pref = [];
        if (c.dietary_restrictions.length) pref.push('Restrições: ' + c.dietary_restrictions.join(', '));
        if (c.allergies.length) pref.push('Alergias: ' + c.allergies.join(', '));
        rows.push('<tr><td>' + (c.name || 'Sem nome') + '</td><td>' + (c.relationship || 'Acompanhante') + '</td><td>' + (c.doc_id || '-') + '</td><td class="d-none d-md-table-cell">' + (pref.length ? pref.join(' · ') : '<span class="text-muted">Sem sinalizações</span>') + '</td></tr>');
    });
    tbody.innerHTML = rows.join('');
}

function renderSelectionOptions(containerId, values, selected, prefix) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var selectedSet = new Set(parseListString(selected).map(function(item) { return String(item).toLowerCase(); }));
    var html = values.map(function(label, idx) {
        var cid = prefix + '_' + idx;
        var checked = selectedSet.has(String(label).toLowerCase()) ? 'checked' : '';
        return '<div class="form-check form-check-inline me-2 mb-1"><input class="form-check-input" type="checkbox" id="' + cid + '" value="' + label + '" ' + checked + '><label class="form-check-label small" for="' + cid + '">' + label + '</label></div>';
    }).join('');
    container.innerHTML = html || '<span class="text-muted small">Sem opções</span>';
}

function collectSelectionOptions(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return [];
    return Array.from(container.querySelectorAll('input[type="checkbox"]:checked')).map(function(input) { return String(input.value || '').trim(); }).filter(Boolean);
}

function renderCompanionEditor() {
    var wrap = document.getElementById('vg_companion_editor_list');
    if (!wrap) return;
    if (!currentCompanionDraft.length) {
        wrap.innerHTML = '<div class="text-muted small border rounded p-2">Nenhum hóspede adicional cadastrado.</div>';
        return;
    }
    var cards = currentCompanionDraft.map(function(c, idx) {
        var base = 'vg_comp_' + idx;
        var dietaryMarkup = dietaryPresetOptions.map(function(opt, i) {
            var id = base + '_diet_' + i;
            var checked = c.dietary_restrictions.map(function(v) { return String(v).toLowerCase(); }).includes(String(opt).toLowerCase()) ? 'checked' : '';
            return '<div class="form-check form-check-inline me-2"><input class="form-check-input" type="checkbox" id="' + id + '" data-role="dietary" data-index="' + idx + '" value="' + opt + '" ' + checked + '><label class="form-check-label small" for="' + id + '">' + opt + '</label></div>';
        }).join('');
        var allergyMarkup = allergyPresetOptions.map(function(opt, i) {
            var id = base + '_allergy_' + i;
            var checked = c.allergies.map(function(v) { return String(v).toLowerCase(); }).includes(String(opt).toLowerCase()) ? 'checked' : '';
            return '<div class="form-check form-check-inline me-2"><input class="form-check-input" type="checkbox" id="' + id + '" data-role="allergies" data-index="' + idx + '" value="' + opt + '" ' + checked + '><label class="form-check-label small" for="' + id + '">' + opt + '</label></div>';
        }).join('');
        var fruitMarkup = fruitPresetOptions.map(function(opt, i) {
            var id = base + '_fruit_' + i;
            var checked = c.breakfast_fruits.map(function(v) { return String(v).toLowerCase(); }).includes(String(opt).toLowerCase()) ? 'checked' : '';
            return '<div class="form-check form-check-inline me-2"><input class="form-check-input" type="checkbox" id="' + id + '" data-role="fruits" data-index="' + idx + '" value="' + opt + '" ' + checked + '><label class="form-check-label small" for="' + id + '">' + opt + '</label></div>';
        }).join('');
        return '<div class="border rounded p-2"><div class="d-flex justify-content-between align-items-center mb-2"><strong>Hóspede adicional ' + (idx + 1) + '</strong><button type="button" class="btn btn-sm btn-outline-danger" data-role="remove-companion" data-index="' + idx + '">Remover</button></div><div class="row g-2"><div class="col-md-6"><input class="form-control form-control-sm" placeholder="Nome" data-role="name" data-index="' + idx + '" value="' + (c.name || '') + '"></div><div class="col-md-3"><input class="form-control form-control-sm" placeholder="Relação" data-role="relationship" data-index="' + idx + '" value="' + (c.relationship || '') + '"></div><div class="col-md-3"><input class="form-control form-control-sm" placeholder="Documento" data-role="doc_id" data-index="' + idx + '" value="' + (c.doc_id || '') + '"></div><div class="col-md-6"><input class="form-control form-control-sm" placeholder="Telefone" data-role="phone" data-index="' + idx + '" value="' + (c.phone || '') + '"></div><div class="col-md-6"><input class="form-control form-control-sm" placeholder="Email" data-role="email" data-index="' + idx + '" value="' + (c.email || '') + '"></div><div class="col-12"><div class="small text-muted mb-1">Restrições alimentares</div>' + dietaryMarkup + '</div><div class="col-12"><div class="small text-muted mb-1">Alergias</div>' + allergyMarkup + '</div><div class="col-12"><input class="form-control form-control-sm" placeholder="Observações alimentares" data-role="food_notes" data-index="' + idx + '" value="' + (c.food_notes || '') + '"></div><div class="col-md-4"><input class="form-control form-control-sm" type="time" data-role="breakfast_time" data-index="' + idx + '" value="' + (c.breakfast_time || '') + '"></div><div class="col-md-8"><input class="form-control form-control-sm" placeholder="Observações do café" data-role="breakfast_notes" data-index="' + idx + '" value="' + (c.breakfast_notes || '') + '"></div><div class="col-12"><div class="small text-muted mb-1">Frutas preferidas</div>' + fruitMarkup + '</div><div class="col-md-4"><div class="form-check mt-2"><input class="form-check-input" type="checkbox" id="' + base + '_birthday" data-role="is_birthday" data-index="' + idx + '" ' + (c.is_birthday ? 'checked' : '') + '><label class="form-check-label small" for="' + base + '_birthday">Aniversariante</label></div></div><div class="col-md-8"><input class="form-control form-control-sm" placeholder="Comemoração especial" data-role="special_celebration" data-index="' + idx + '" value="' + (c.special_celebration || '') + '"></div><div class="col-12"><input class="form-control form-control-sm" placeholder="Observações de hospitalidade" data-role="hospitality_notes" data-index="' + idx + '" value="' + (c.hospitality_notes || '') + '"></div></div></div>';
    });
    wrap.innerHTML = cards.join('');
}

function syncCompanionDraftFromEditor() {
    var wrap = document.getElementById('vg_companion_editor_list');
    if (!wrap) return;
    currentCompanionDraft = currentCompanionDraft.map(function(c, idx) {
        var scoped = function(role) { return wrap.querySelector('[data-role="' + role + '"][data-index="' + idx + '"]'); };
        var collectChecks = function(role) {
            return Array.from(wrap.querySelectorAll('input[data-role="' + role + '"][data-index="' + idx + '"]:checked')).map(function(input) { return String(input.value || '').trim(); }).filter(Boolean);
        };
        return {
            id: c.id,
            name: scoped('name') ? scoped('name').value.trim() : '',
            relationship: scoped('relationship') ? scoped('relationship').value.trim() : '',
            doc_id: scoped('doc_id') ? scoped('doc_id').value.trim() : '',
            phone: scoped('phone') ? scoped('phone').value.trim() : '',
            email: scoped('email') ? scoped('email').value.trim() : '',
            dietary_restrictions: collectChecks('dietary'),
            allergies: collectChecks('allergies'),
            food_notes: scoped('food_notes') ? scoped('food_notes').value.trim() : '',
            breakfast_time: scoped('breakfast_time') ? scoped('breakfast_time').value.trim() : '',
            breakfast_fruits: collectChecks('fruits'),
            breakfast_notes: scoped('breakfast_notes') ? scoped('breakfast_notes').value.trim() : '',
            is_birthday: scoped('is_birthday') ? Boolean(scoped('is_birthday').checked) : false,
            special_celebration: scoped('special_celebration') ? scoped('special_celebration').value.trim() : '',
            hospitality_notes: scoped('hospitality_notes') ? scoped('hospitality_notes').value.trim() : ''
        };
    }).filter(function(c) { return c.name || c.doc_id || c.phone || c.email; });
}

function populateGuestModal(responseData, roomNum, reservationId, context) {
    var guest = responseData.guest || {};
    var reservation = responseData.reservation || {};
    var personal = guest.personal_info || {};
    var fiscal = guest.fiscal_info || {};
    var history = guest.history || [];
    var operational = guest.operational_info || {};
    var companions = Array.isArray(guest.companions) ? guest.companions.map(sanitizeCompanion) : [];
    var contextData = context || {};
    currentGuestPayload = {
        reservationId: reservationId || reservation.id || '',
        personal: personal,
        fiscal: fiscal,
        operational: operational,
        companions: companions,
        reservation: reservation,
        context: contextData
    };
    currentCompanionDraft = companions.map(function(c, idx) { return sanitizeCompanion(c, idx); });

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
    setText('vg_guest_count', String(1 + companions.length));

    var stayFinancial = responseData.reservation_financial || {};
    var consFinancial = responseData.consumption_financial || {};
    setText('vg_stay_total', formatCurrency(parseFloat(stayFinancial.total || reservation.amount || 0)));
    setText('vg_stay_paid', formatCurrency(parseFloat(stayFinancial.paid || reservation.paid_amount || 0)));
    setText('vg_stay_balance', formatCurrency(parseFloat(stayFinancial.pending || reservation.to_receive || 0)));
    setText('vg_cons_total', formatCurrency(parseFloat(consFinancial.total || 0)));
    setText('vg_cons_paid', formatCurrency(parseFloat(consFinancial.paid || 0)));
    setText('vg_cons_balance', formatCurrency(parseFloat(consFinancial.pending || 0)));

    var dietary = parseListString(operational.dietary_restrictions);
    var allergies = parseListString(operational.allergies || operational.allergies_list);
    var breakfastStart = operational.breakfast_time_start || '--:--';
    var breakfastEnd = operational.breakfast_time_end || '--:--';
    var breakfastStandard = operational.breakfast_time_standard || '';
    if (!breakfastStandard && (operational.breakfast_time_start || operational.breakfast_time_end)) {
        breakfastStandard = `${breakfastStart} - ${breakfastEnd}`;
    }
    var commemorative = parseListString(operational.commemorative_dates);
    var specialCelebration = String(operational.special_celebration || '').trim();
    if (specialCelebration && !commemorative.includes(specialCelebration)) commemorative.unshift(specialCelebration);
    var breakfastFruits = parseListString(operational.breakfast_fruit_preferences);
    var foodNotes = String(operational.food_notes || '').trim();
    var breakfastNotes = String(operational.breakfast_notes || '').trim();
    var hospitalityNotes = String(operational.hospitality_notes || '').trim();
    var recurrence = guest.recurrence_summary || {};
    setText('vg_allergies', allergies.length ? allergies.join(', ') : '-');
    setText('vg_dietary', dietary.length ? dietary.join(', ') : '-');
    setText('vg_food_notes', foodNotes || '-');
    setText('vg_breakfast', breakfastStandard || ((operational.breakfast_time_start || operational.breakfast_time_end) ? `${breakfastStart} - ${breakfastEnd}` : '-'));
    setText('vg_breakfast_fruits', breakfastFruits.length ? breakfastFruits.join(', ') : '-');
    setText('vg_breakfast_notes', breakfastNotes || '-');
    setText('vg_is_birthday', parseBoolean(operational.is_birthday || operational.birthday_flag) ? 'Sim' : 'Não');
    setText('vg_commemorative', commemorative.length ? commemorative.join(', ') : '-');
    setText('vg_hospitality_notes', hospitalityNotes || operational.service_notes || '-');
    setText('vg_vip', operational.vip_note || operational.service_notes || '-');
    setText('vg_recurrence', recurrence.stays_count ? (`${recurrence.stays_count} estadias`) : 'Primeira estadia');
    setText('vg_last_update_at', operational.last_updated_at || '-');
    setText('vg_last_update_by', operational.last_updated_by || '-');
    setText('vg_last_update_source', operational.last_updated_source || '-');
    renderHospitalityBadges(operational, companions);
    renderGuestList(personal, companions);

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
    setInputValue('vg_edit_allergies', parseListString(operational.allergies || operational.allergies_list).join(', '));
    setInputValue('vg_edit_dietary', parseListString(operational.dietary_restrictions).join(', '));
    setInputValue('vg_edit_food_notes', operational.food_notes || '');
    setInputValue('vg_edit_breakfast_start', operational.breakfast_time_start || '');
    setInputValue('vg_edit_breakfast_end', operational.breakfast_time_end || '');
    setInputValue('vg_edit_breakfast_time_standard', operational.breakfast_time_standard || '');
    setInputValue('vg_edit_breakfast_notes', operational.breakfast_notes || '');
    var birthdayEl = document.getElementById('vg_edit_is_birthday');
    if (birthdayEl) birthdayEl.checked = parseBoolean(operational.is_birthday || operational.birthday_flag);
    setInputValue('vg_edit_special_celebration', operational.special_celebration || '');
    setInputValue('vg_edit_commemorative', parseListString(operational.commemorative_dates).join(', '));
    setInputValue('vg_edit_vip', operational.vip_note || '');
    setInputValue('vg_edit_hospitality_notes', operational.hospitality_notes || operational.service_notes || '');
    renderSelectionOptions('vg_edit_dietary_options', dietaryPresetOptions, parseListString(operational.dietary_restrictions), 'vg_dietary');
    renderSelectionOptions('vg_edit_allergies_options', allergyPresetOptions, parseListString(operational.allergies || operational.allergies_list), 'vg_allergies');
    renderSelectionOptions('vg_edit_fruits_options', fruitPresetOptions, parseListString(operational.breakfast_fruit_preferences), 'vg_fruits');
    currentCompanionDraft = (currentGuestPayload.companions || []).map(function(c, idx) { return sanitizeCompanion(c, idx); });
    renderCompanionEditor();

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

    syncCompanionDraftFromEditor();
    setInputValue('vg_edit_dietary', collectSelectionOptions('vg_edit_dietary_options').join(', '));
    setInputValue('vg_edit_allergies', collectSelectionOptions('vg_edit_allergies_options').join(', '));
    var breakfastStartRaw = document.getElementById('vg_edit_breakfast_start').value.trim();
    var breakfastEndRaw = document.getElementById('vg_edit_breakfast_end').value.trim();
    var breakfastStandardRaw = document.getElementById('vg_edit_breakfast_time_standard').value.trim();
    if (!isValidHHMM(breakfastStartRaw) || !isValidHHMM(breakfastEndRaw) || !isValidHHMM(breakfastStandardRaw)) {
        alert('Horário de café inválido. Use HH:MM.');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Salvar Ficha';
        }
        return;
    }
    if (breakfastStartRaw && breakfastEndRaw && breakfastEndRaw < breakfastStartRaw) {
        alert('Horário de café inconsistente: fim anterior ao início.');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Salvar Ficha';
        }
        return;
    }
    var companionSignatures = new Set();
    for (var i = 0; i < currentCompanionDraft.length; i++) {
        var c = currentCompanionDraft[i];
        var sig = normalizeText(c.doc_id, 40).toLowerCase() || normalizeText(c.email, 120).toLowerCase() || normalizeText(c.phone, 24).replace(/\D+/g, '') || normalizeText(c.name, 120).toLowerCase();
        if (!sig) continue;
        if (companionSignatures.has(sig)) {
            alert('Existem hóspedes duplicados na lista de acompanhantes.');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Salvar Ficha';
            }
            return;
        }
        companionSignatures.add(sig);
    }
    var personal = {
        name: normalizeText(document.getElementById('vg_edit_name').value, 120),
        doc_id: normalizeText(document.getElementById('vg_edit_doc').value, 40),
        birth_date: normalizeText(document.getElementById('vg_edit_birth').value, 20),
        email: normalizeText(document.getElementById('vg_edit_email').value, 120),
        phone: normalizeText(document.getElementById('vg_edit_phone').value, 24),
        address: normalizeText(document.getElementById('vg_edit_address').value, 180),
        city: normalizeText(document.getElementById('vg_edit_city').value, 80),
        state: normalizeText(document.getElementById('vg_edit_state').value, 2).toUpperCase()
    };
    var fiscalDoc = normalizeText(document.getElementById('vg_edit_fiscal_doc').value, 20);
    var fiscal = {
        cpf_cnpj: fiscalDoc,
        razao_social: normalizeText(document.getElementById('vg_edit_fiscal_name').value, 120)
    };
    var allergiesList = collectSelectionOptions('vg_edit_allergies_options');
    var dietaryList = collectSelectionOptions('vg_edit_dietary_options');
    var fruitList = collectSelectionOptions('vg_edit_fruits_options');
    var commemorativeList = parseListString(document.getElementById('vg_edit_commemorative').value).slice(0, 8).map(function(item) { return normalizeText(item, 80); });
    var specialCelebration = normalizeText(document.getElementById('vg_edit_special_celebration').value, 120);
    if (specialCelebration && !commemorativeList.includes(specialCelebration)) commemorativeList.unshift(specialCelebration);
    var operational = {
        allergies: allergiesList.join(', '),
        allergies_list: allergiesList,
        dietary_restrictions: dietaryList,
        food_notes: normalizeText(document.getElementById('vg_edit_food_notes').value, 300),
        breakfast_time_start: breakfastStartRaw,
        breakfast_time_end: breakfastEndRaw,
        breakfast_time_standard: breakfastStandardRaw,
        breakfast_fruit_preferences: fruitList,
        breakfast_notes: normalizeText(document.getElementById('vg_edit_breakfast_notes').value, 300),
        is_birthday: Boolean(document.getElementById('vg_edit_is_birthday').checked),
        birthday_flag: Boolean(document.getElementById('vg_edit_is_birthday').checked),
        special_celebration: specialCelebration,
        commemorative_dates: commemorativeList,
        vip_note: normalizeText(document.getElementById('vg_edit_vip').value, 220),
        hospitality_notes: normalizeText(document.getElementById('vg_edit_hospitality_notes').value, 300),
        service_notes: normalizeText(document.getElementById('vg_edit_hospitality_notes').value, 300)
    };

    fetch('/api/guest/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            reservation_id: currentGuestPayload.reservationId,
            personal_info: personal,
            fiscal_info: fiscal,
            operational_info: operational,
            companions: currentCompanionDraft,
            source: (currentGuestContext && currentGuestContext.source) ? currentGuestContext.source : 'unknown'
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

document.addEventListener('click', function(event) {
    var target = event.target;
    if (!target) return;
    if (target.id === 'vg_add_companion_btn') {
        currentCompanionDraft.push(sanitizeCompanion({}, currentCompanionDraft.length));
        renderCompanionEditor();
        return;
    }
    var removeIndex = target.getAttribute('data-index');
    if (target.getAttribute('data-role') === 'remove-companion' && removeIndex !== null) {
        var idx = parseInt(removeIndex, 10);
        if (!Number.isNaN(idx)) {
            currentCompanionDraft.splice(idx, 1);
            renderCompanionEditor();
        }
    }
});

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
