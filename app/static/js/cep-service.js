/**
 * CEP Service - Auto-fill address from CEP
 * Uses backend proxy: /api/common/cep/<cep>
 */

const CepService = {
    /**
     * Binds CEP lookup to input fields
     * @param {string} cepId - ID of CEP input
     * @param {string} streetId - ID of Street input
     * @param {string} neighborhoodId - ID of Neighborhood input
     * @param {string} cityId - ID of City input
     * @param {string} stateId - ID of State input
     * @param {string} numberId - ID of Number input (to focus after success)
     */
    bind: function(cepId, streetId, neighborhoodId, cityId, stateId, numberId) {
        const cepInput = document.getElementById(cepId);
        if (!cepInput) return;

        cepInput.addEventListener('blur', function() {
            const cep = this.value.replace(/\D/g, '');
            
            if (cep.length === 8) {
                // Show loading state?
                document.body.style.cursor = 'wait';
                
                fetch(`/api/common/cep/${cep}`)
                    .then(response => response.json())
                    .then(data => {
                        document.body.style.cursor = 'default';
                        
                        if (data.valid) {
                            const addr = data.data;
                            if (streetId) setVal(streetId, addr.street);
                            if (neighborhoodId) setVal(neighborhoodId, addr.neighborhood);
                            if (cityId) setVal(cityId, addr.city);
                            if (stateId) setVal(stateId, addr.state);
                            
                            // Focus Number
                            if (numberId) {
                                const numInput = document.getElementById(numberId);
                                if (numInput) numInput.focus();
                            }
                        } else {
                            alert(data.message || 'CEP não encontrado.');
                        }
                    })
                    .catch(err => {
                        document.body.style.cursor = 'default';
                        console.error('CEP Error:', err);
                        alert('Erro ao consultar CEP.');
                    });
            }
        });
        
        function setVal(id, val) {
            const el = document.getElementById(id);
            if (el) el.value = val;
        }
    }
};

// Auto-init if using data attributes (optional future usage)
// Example: <input class="cep-search" data-street="logradouro" ...>
