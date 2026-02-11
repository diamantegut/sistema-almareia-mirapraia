
    // Guest View Logic
    var currentGuestRoom = null;

    function openViewGuestModal(guestId, guestName, roomNum) {
        currentGuestRoom = roomNum;
        
        var modalEl = document.getElementById('viewGuestModal');
        var modal = new bootstrap.Modal(modalEl);
        
        // Reset UI
        document.getElementById('viewGuestLoading').classList.remove('d-none');
        document.getElementById('viewGuestContent').classList.add('d-none');
        document.getElementById('viewGuestError').classList.add('d-none');
        
        // Show Modal
        modal.show();
        
        // Fetch Data
        if (!guestId || guestId === 'None') {
            showGuestError("ID do hóspede não encontrado. É um registro antigo?");
            return;
        }

        fetch('/api/guest/details/' + guestId)
            .then(response => {
                if (!response.ok) throw new Error("Hóspede não encontrado");
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error(data.error || "Erro desconhecido");
                populateGuestModal(data.data, roomNum);
            })
            .catch(err => {
                console.error(err);
                showGuestError(err.message);
            });
    }

    function populateGuestModal(responseData, roomNum) {
        var guest = responseData.guest;
        var history = responseData.history;
        
        // Personal Info
        setText('vg_name', guest.personal_info.name);
        setText('vg_ficha', guest.ficha_number || 'N/A');
        setText('vg_doc', guest.personal_info.doc_id || 'Não informado');
        setText('vg_birth', guest.personal_info.birth_date || '-');
        setText('vg_email', guest.personal_info.contact?.email || '-');
        setText('vg_phone', guest.personal_info.contact?.phone || '-');
        
        var addr = guest.personal_info.address || {};
        var addrStr = [addr.street, addr.city, addr.state].filter(Boolean).join(', ');
        setText('vg_address', addrStr || 'Endereço não cadastrado');

        // Stay Info
        setText('vg_room', roomNum);
        setText('vg_status', 'Hospedado'); 
        setText('vg_checkin', guest.stay_info?.checkin_date || '-');
        setText('vg_checkout', guest.stay_info?.checkout_date || '-');
        
        // Financials 
        var financials = guest.financials || {};
        setText('vg_total_consumed', formatCurrency(financials.amount_due || 0));
        setText('vg_total_paid', formatCurrency(financials.paid_amount || 0));
        setText('vg_balance', formatCurrency(financials.balance || 0));

        // History
        var tbody = document.getElementById('vg_history_table');
        tbody.innerHTML = '';
        if (history && history.length > 0) {
            history.forEach(h => {
                // Filter out current stay if desired, or keep all
                var statusMap = {
                    'active': 'Hospedado',
                    'checked_out': 'Finalizado',
                    'cancelled': 'Cancelado'
                };
                var statusLabel = statusMap[h.status] || h.status || 'N/A';
                
                var tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${h.checkin || '-'}</td>
                    <td>${h.room || '-'}</td>
                    <td>${formatCurrency(h.total || 0)}</td>
                    <td><span class="badge bg-secondary">${statusLabel}</span></td>
                `;
                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Nenhum histórico encontrado.</td></tr>';
        }

        // Show Content
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

    function formatCurrency(val) {
        return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
    }

    function viewDetailedCharges() {
        // Close guest modal and open charges modal
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

    function switchToEdit() {
         // Logic to switch to edit mode or open the edit modal
         // For now, let's just trigger the existing openEditGuestModal
         var guestModalEl = document.getElementById('viewGuestModal');
         var guestModal = bootstrap.Modal.getInstance(guestModalEl);
         guestModal.hide();
         
         setTimeout(() => {
             var name = document.getElementById('vg_name').textContent;
             openEditGuestModal(currentGuestRoom, name);
         }, 500);
    }
