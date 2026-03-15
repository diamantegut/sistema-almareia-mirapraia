
// Constants
const DEFAULT_CATEGORIES = [
    "Lençol Solteiro", "Lençol Casal", "Lençol King", "Fronha", "Capa Edredom",
    "Toalha Banho", "Toalha Rosto", "Piso", "Toalha Piscina",
    "Roupão P", "Roupão M", "Roupão G", "Roupão GG",
    "Tapete", "Cortina", "Travesseiro"
];
const DEFAULT_CATEGORY_OPTIONS = {
    "Lençol Solteiro": ["Lençol Solteiro"],
    "Lençol Casal": ["Lençol Casal"],
    "Lençol King": ["Lençol King"],
    "Fronha": ["Fronha"],
    "Capa Edredom": ["Capa Edredom"],
    "Toalha Banho": ["Toalha Banho"],
    "Toalha Rosto": ["Toalha Rosto"],
    "Piso": ["Piso"],
    "Toalha Piscina": ["Toalha Piscina"],
    "Roupão P": ["Roupão P"],
    "Roupão M": ["Roupão M"],
    "Roupão G": ["Roupão G"],
    "Roupão GG": ["Roupão GG"],
    "Tapete": ["Tapete"],
    "Cortina": ["Cortina"],
    "Travesseiro": ["Travesseiro"]
};

// State
let state = {
    scans: [],
    products: {},
    bagHistory: [],
    brands: [],
    categories: [...DEFAULT_CATEGORIES],
    categoryOptions: JSON.parse(JSON.stringify(DEFAULT_CATEGORY_OPTIONS)),
    categoryPrices: {}
};

let groupScans = [];
let debounceTimer = null;

// DOM Elements
const els = {
    input: document.getElementById("scanInput"),
    rows: document.getElementById("rows"),
    total: document.getElementById("totalScans"),
    unique: document.getElementById("uniqueCount"),
    dup: document.getElementById("duplicateCount"),
    uniqueOnly: document.getElementById("uniqueOnly"),
    autoCapture: document.getElementById("autoCapture"),
    streamMode: document.getElementById("streamMode"),
    bagName: document.getElementById("bagName"),
    brandList: document.getElementById("brandList"),
    
    // Buttons
    newBagBtn: document.getElementById("newBagBtn"),
    clearBagBtn: document.getElementById("clearBagBtn"),
    exportBagExcelBtn: document.getElementById("exportBagExcelBtn"),
    groupRegBtn: document.getElementById("groupRegBtn"),
    addBrandBtn: document.getElementById("addBrandBtn"),
    fullSetBtn: document.getElementById("fullSetBtn"),
    manageCategoriesBtn: document.getElementById("manageCategoriesBtn"),

    // Modals
    productModal: document.getElementById("productModal"),
    groupRegisterModal: document.getElementById("groupRegisterModal"),
    fullSetModal: document.getElementById("fullSetModal"),
    
    // Product Modal Fields
    pmRfid: document.getElementById("pmRfid"),
    pmCategory: document.getElementById("pmCategory"),
    pmName: document.getElementById("pmName"), 
    pmVariant: document.getElementById("pmVariant"),
    pmBrand: document.getElementById("pmBrand"),
    pmAcqDate: document.getElementById("pmAcqDate"),
    pmPrice: document.getElementById("pmPrice"),
    pmItemPrice: document.getElementById("pmItemPrice"),
    pmDestination: document.getElementById("pmDestination"),
    pmSave: document.getElementById("pmSave"),
    pmCancel: document.getElementById("pmCancel"),
    pmVariantContainer: document.getElementById("pmVariantContainer"),

    // Group Modal Fields
    grCategory: document.getElementById("grCategory"),
    grName: document.getElementById("grName"),
    grVariant: document.getElementById("grVariant"),
    grBrand: document.getElementById("grBrand"),
    grPrice: document.getElementById("grPrice"),
    grItemPrice: document.getElementById("grItemPrice"),
    grAcqDate: document.getElementById("grAcqDate"), // Added
    grDestination: document.getElementById("grDestination"),
    grScanInput: document.getElementById("grScanInput"),
    grList: document.getElementById("grList"),
    grCount: document.getElementById("grCount"),
    grSave: document.getElementById("grSave"),
    grCancel: document.getElementById("grCancel"),
    grVariantContainer: document.getElementById("grVariantContainer"),

    // Full Set Fields
    fsRows: document.getElementById("fsRows")
};

// --- API Interaction ---

// --- Storage (LocalStorage for Persistence) ---

function persist() {
    try {
        const payload = {
            scans: state.scans,
            bagName: els.bagName ? els.bagName.value : "Bag 1",
            products: state.products,
            bagHistory: state.bagHistory,
            brands: state.brands,
            categories: state.categories,
            categoryOptions: state.categoryOptions
        };
        localStorage.setItem("laundry-counter", JSON.stringify(payload));
        // Also try API if available, but don't block
        fetch('/api/laundry/data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(state)
        }).catch(e => console.warn("API save failed, using LocalStorage only"));
    } catch (e) { console.error("Persist failed:", e); }
}

function restore() {
    try {
        // Try LocalStorage first (User's local state)
        const raw = localStorage.getItem("laundry-counter");
        if (raw) {
            const data = JSON.parse(raw);
            if (data) {
                state = { ...state, ...data };
                // Ensure defaults
                if (!state.categories || state.categories.length === 0) state.categories = [...DEFAULT_CATEGORIES];
                if (!state.categoryOptions || Object.keys(state.categoryOptions).length === 0) state.categoryOptions = JSON.parse(JSON.stringify(DEFAULT_CATEGORY_OPTIONS));
                if (!state.products) state.products = {};
                if (!state.scans) state.scans = [];
                if (!state.brands) state.brands = [];
            }
        } else {
             // Fallback to API if LocalStorage empty
             fetch('/api/laundry/data')
                .then(r => r.json())
                .then(data => {
                    if(data) {
                        state = { ...state, ...data };
                        render();
                        updateBagNameUI();
                        renderBrandList();
                    }
                })
                .catch(e => console.warn("API restore failed"));
        }
        
        render();
        updateBagNameUI();
        renderBrandList();
    } catch (e) {
        console.error("Restore failed:", e);
    }
}

// --- Core Logic ---

function setupInput() {
    // Main Scanner Input
    els.input.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            const val = els.input.value.trim().toUpperCase();
            if (val) addScan(val);
            els.input.value = "";
        }
    });

    els.input.addEventListener("input", () => {
        const val = els.input.value.trim().toUpperCase();
        // Auto-submit if 24 chars (standard RFID hex) AND starts with 'E'
        if (val.length === 24 && val.startsWith('E')) {
            addScan(val);
            els.input.value = "";
        }
    });

    // Group Modal Input
    if (els.grScanInput) {
        els.grScanInput.addEventListener("keydown", e => {
            if (e.key === "Enter") {
                const val = els.grScanInput.value.trim().toUpperCase();
                if (val && val.length === 24 && val.startsWith('E')) addGroupScan(val);
                els.grScanInput.value = "";
            }
        });

        els.grScanInput.addEventListener("input", () => {
            const val = els.grScanInput.value.trim().toUpperCase();
            if (val.length === 24 && val.startsWith('E')) {
                addGroupScan(val);
                els.grScanInput.value = "";
            }
        });
    }
}

function addScan(rfid) {
    // Check duplication in current active list
    const existingInList = state.scans.find(s => s.rfid === rfid);
    
    // Automatic Duplicate Rejection (Always Active)
    if (existingInList) {
        console.warn("Duplicate rejected:", rfid);
        return; 
    }

    const now = new Date();
    const scan = {
        rfid,
        timestamp: now.toISOString(),
        bag: els.bagName.value || "Sem Sacola"
    };

    state.scans.unshift(scan);
    checkProduct(rfid);
    persist();
    render();
}

function checkProduct(rfid) {
    if (!state.products[rfid]) {
        // New product detected - Auto open registration modal
        // Small delay to allow UI to render the scan row first
        setTimeout(() => {
            openProductModal(rfid);
        }, 200);
    }
}

// --- Bag Management ---

function getTodayStr() {
    const d = new Date();
    const yy = d.getFullYear().toString().slice(-2);
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${dd}-${mm}-${yy}`;
}

function updateBagNameUI() {
    const todayStr = getTodayStr(); // DD-MM-YY
    
    // Find highest sequence number for today in history
    let maxSeq = 0;
    state.bagHistory.forEach(bag => {
        if (bag.name.startsWith(todayStr)) {
            const parts = bag.name.split(' ');
            if (parts.length > 1) {
                const seq = parseInt(parts[1]);
                if (!isNaN(seq) && seq > maxSeq) maxSeq = seq;
            }
        }
    });

    // Next sequence
    const nextSeq = String(maxSeq + 1).padStart(2, '0');
    const bagName = `${todayStr} ${nextSeq}`;
    
    els.bagName.value = bagName;
    els.bagName.disabled = true; // Lock it
}

if (els.newBagBtn) {
    els.newBagBtn.addEventListener("click", () => {
        const name = els.bagName.value;
        if (!name) return;
        
        const bagItems = [...state.scans]; // Copy current scans
        
        if (bagItems.length === 0) {
            return alert("Nenhum item nesta sacola.");
        }
        
        if (confirm(`Fechar sacola "${name}" e arquivar itens?`)) {
            // Save to history
            state.bagHistory.push({
                name: name,
                date: new Date().toISOString(),
                count: bagItems.length,
                items: bagItems
            });
            
            // Clear current view (Archive)
            state.scans = [];
            
            persist();
            render();
            
            // Generate next name
            updateBagNameUI();
        }
    });
}

if (els.clearBagBtn) {
    els.clearBagBtn.addEventListener("click", () => {
        if (confirm("Limpar lista de leitura atual? (Isso não apaga o cadastro dos itens)")) {
            state.scans = [];
            persist();
            render();
        }
    });
}

// --- Brand Management ---

function renderBrandList() {
    if (els.brandList) {
        // Unique brands from state + products
        const allBrands = new Set(state.brands || []);
        Object.values(state.products).forEach(p => {
            if (p.brand) allBrands.add(p.brand);
        });
        
        els.brandList.innerHTML = Array.from(allBrands).sort().map(b => `<option value="${b}">`).join("");
    }
}

if (els.addBrandBtn) {
    els.addBrandBtn.addEventListener("click", () => {
        const brand = prompt("Digite o nome da nova marca:");
        if (brand) {
            if (!state.brands) state.brands = [];
            if (!state.brands.includes(brand)) {
                state.brands.push(brand);
                state.brands.sort();
                persist();
                renderBrandList();
                alert(`Marca "${brand}" adicionada.`);
            } else {
                alert("Esta marca já existe.");
            }
        }
    });
}

// --- UI Rendering ---

function render() {
    const unique = new Set(state.scans.map(s => s.rfid)).size;
    if(els.total) els.total.textContent = state.scans.length;
    if(els.unique) els.unique.textContent = unique;
    if(els.dup) els.dup.textContent = state.scans.length - unique;

    if(els.rows) {
        els.rows.innerHTML = state.scans.slice(0, 50).map((scan, i) => {
            const prod = state.products[scan.rfid] || {};
            const isNew = !prod.name;
            const time = new Date(scan.timestamp).toLocaleTimeString();
            
            return `
                <tr>
                    <td>${state.scans.length - i}</td>
                    <td style="font-family: monospace">${scan.rfid}</td>
                    <td>${prod.name || '<span class="text-danger fw-bold">Novo Item</span>'}</td>
                    <td>${prod.brand || '-'}</td>
                    <td>${prod.category || '-'}</td>
                    <td>${prod.variant || '-'}</td>
                    <td>${scan.bag}</td>
                    <td>${time}</td>
                    <td>${isNew ? '<span class="badge bg-warning text-dark">Cadastro Pendente</span>' : '<span class="badge bg-success">OK</span>'}</td>
                    <td>
                        <button onclick="editProduct('${scan.rfid}')" class="btn btn-sm btn-outline-primary"><i class="bi bi-pencil"></i></button>
                        <button onclick="removeScan('${scan.rfid}')" class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button>
                    </td>
                </tr>
            `;
        }).join("");
    }
}

window.removeScan = (rfid) => {
    if (confirm("Remover este scan?")) {
        const idx = state.scans.findIndex(s => s.rfid === rfid);
        if (idx > -1) {
            state.scans.splice(idx, 1);
            persist();
            render();
        }
    }
};

window.editProduct = (rfid) => {
    openProductModal(rfid);
};

// --- Shared Helper for Dropdowns ---

function populateCategorySelect(selectEl) {
    if (!state.categories || state.categories.length === 0) {
        state.categories = [...DEFAULT_CATEGORIES];
    }
    selectEl.innerHTML = state.categories.map(c => `<option value="${c}">${c}</option>`).join("");
}

function populateNameSelect(selectEl, category) {
    const opts = state.categoryOptions[category] || [];
    if (opts.length === 0) {
        selectEl.innerHTML = '<option value="">Sem itens</option>';
    } else {
        selectEl.innerHTML = opts.map(o => `<option value="${o}">${o}</option>`).join("");
    }
}

// --- Product Modal ---

let currentEditingRfid = null;

function openProductModal(rfid) {
    currentEditingRfid = rfid;
    const prod = state.products[rfid] || {};
    
    els.pmRfid.value = rfid;
    
    // Setup Categories
    populateCategorySelect(els.pmCategory);
    els.pmCategory.value = prod.category || state.categories[0];
    
    // Setup Name
    populateNameSelect(els.pmName, els.pmCategory.value);
    if (prod.name) els.pmName.value = prod.name;
    
    // Listen for category change
    els.pmCategory.onchange = () => {
        populateNameSelect(els.pmName, els.pmCategory.value);
    };

    els.pmBrand.value = prod.brand || "";
    els.pmAcqDate.value = prod.acqDate || new Date().toISOString().slice(0, 10);
    els.pmPrice.value = prod.washPrice || 0;
    els.pmItemPrice.value = prod.itemPrice || 0;
    els.pmDestination.value = prod.destination || "Almareia";
    
    // Variant (Hidden for now as 'Name' covers most use cases, but kept in data)
    if (els.pmVariantContainer) els.pmVariantContainer.style.display = 'none';

    // Show modal
    const bsModal = new bootstrap.Modal(els.productModal);
    bsModal.show();
}

if (els.pmSave) {
    els.pmSave.addEventListener("click", () => {
        if (!currentEditingRfid) return;
        
        state.products[currentEditingRfid] = {
            rfid: currentEditingRfid,
            category: els.pmCategory.value,
            name: els.pmName.value, 
            variant: "", // Deprecated/Unused for now
            brand: els.pmBrand.value,
            acqDate: els.pmAcqDate.value,
            washPrice: parseFloat(els.pmPrice.value) || 0,
            itemPrice: parseFloat(els.pmItemPrice.value) || 0,
            destination: els.pmDestination.value,
            status: "ativo"
        };
        
        persist();
        const bsModal = bootstrap.Modal.getInstance(els.productModal);
        bsModal.hide();
        render();
        renderBrandList(); // Update brands if new one typed
    });
}

// --- Group Modal Logic ---

if (els.groupRegBtn) {
    els.groupRegBtn.addEventListener("click", () => {
        // Open Modal
        groupScans = [];
        updateGroupList();
        
        // Setup initial values
        populateCategorySelect(els.grCategory);
        populateNameSelect(els.grName, els.grCategory.value);
        
        els.grCategory.onchange = () => {
            populateNameSelect(els.grName, els.grCategory.value);
        };
        
        // Set Default Date
        if (els.grAcqDate) {
            els.grAcqDate.value = new Date().toISOString().slice(0, 10);
        }

        const bsModal = new bootstrap.Modal(els.groupRegisterModal);
        bsModal.show();
        
        // Focus input after delay
        setTimeout(() => els.grScanInput.focus(), 500);
    });
}

function addGroupScan(rfid) {
    if (groupScans.includes(rfid)) return; // Auto reject duplicate in group
    groupScans.unshift(rfid);
    updateGroupList();
}

function updateGroupList() {
    els.grCount.textContent = groupScans.length;
    els.grList.innerHTML = groupScans.map((rfid, i) => `
        <div class="d-flex justify-content-between align-items-center border-bottom py-1 px-2">
            <span class="font-monospace small">${rfid}</span>
            <button class="btn btn-sm text-danger" onclick="removeGroupScan('${rfid}')">&times;</button>
        </div>
    `).join("");
}

window.removeGroupScan = (rfid) => {
    groupScans = groupScans.filter(r => r !== rfid);
    updateGroupList();
};

if (els.grSave) {
    els.grSave.addEventListener("click", () => {
        if (groupScans.length === 0) return alert("Nenhuma tag escaneada.");
        
        const commonData = {
            category: els.grCategory.value,
            name: els.grName.value,
            variant: "",
            brand: els.grBrand.value,
            washPrice: parseFloat(els.grPrice.value) || 0,
            itemPrice: parseFloat(els.grItemPrice.value) || 0,
            destination: els.grDestination.value,
            acqDate: els.grAcqDate ? els.grAcqDate.value : new Date().toISOString().slice(0, 10),
            status: "ativo"
        };
        
        // Apply to all
        groupScans.forEach(rfid => {
            state.products[rfid] = {
                rfid,
                ...commonData
            };
            
            // Add to main scan list if not present
            const existingScan = state.scans.find(s => s.rfid === rfid);
            if (!existingScan) {
                state.scans.unshift({
                    rfid,
                    timestamp: new Date().toISOString(),
                    bag: els.bagName.value || "Sem Sacola"
                });
            }
        });
        
        persist();
        const bsModal = bootstrap.Modal.getInstance(els.groupRegisterModal);
        bsModal.hide();
        render();
        renderBrandList();
        alert(`${groupScans.length} itens registrados com sucesso!`);
    });
}

// --- Full Set / Enchoval Completo ---

if (els.fullSetBtn) {
    els.fullSetBtn.addEventListener("click", () => {
        renderFullSet();
        const bsModal = new bootstrap.Modal(els.fullSetModal);
        bsModal.show();
    });
}

function renderFullSet() {
    if (!els.fsRows) return;
    
    const allProducts = Object.values(state.products);
    // Sort by name then category
    allProducts.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    
    els.fsRows.innerHTML = allProducts.map(p => `
        <tr>
            <td>${p.category || '-'}</td>
            <td>${p.name || '-'}</td>
            <td>${p.variant || '-'}</td>
            <td class="font-monospace small">${p.rfid}</td>
            <td>${p.destination || '-'}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="editProductFromFullSet('${p.rfid}')">
                    <i class="bi bi-pencil"></i>
                </button>
            </td>
        </tr>
    `).join("");
}

window.editProductFromFullSet = (rfid) => {
    // Close full set modal first? Or open on top? Bootstrap supports stacked modals but it can be tricky.
    // Ideally close full set, open product, and when product closes, maybe reopen full set?
    // For simplicity, let's just open the product modal on top.
    
    const fsModalEl = document.getElementById('fullSetModal');
    const fsModal = bootstrap.Modal.getInstance(fsModalEl);
    if(fsModal) fsModal.hide();
    
    setTimeout(() => {
        openProductModal(rfid);
    }, 200);
};


// --- Init ---

setupInput();
restore();
