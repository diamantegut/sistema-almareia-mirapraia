from datetime import datetime, timedelta
from app.services.data_service import (
    load_stock_requests, load_products, load_stock_entries, 
    load_stock_transfers, load_stock_logs
)

def calculate_suggested_min_stock():
    """
    Calculates suggested minimum stock based on monthly consumption averages.
    Returns a list of dicts:
    [{'product': name, 'current_min': val, 'avg_monthly': val, 'suggested_min': val, 'diff': val}, ...]
    """
    requests = load_stock_requests()
    products = load_products()
    
    # Calculate total consumption per product (last 3 months ideally, but using all history for simplicity if limited data)
    # Let's filter for last 90 days to be more accurate
    
    today = datetime.now()
    start_date = today - timedelta(days=90)
    
    consumption_totals = {}
    
    for req in requests:
        try:
            req_date = datetime.strptime(req['date'], '%d/%m/%Y')
            if req_date >= start_date:
                # Process items
                if 'items_structured' in req:
                    for item in req['items_structured']:
                        name = item['name']
                        qty = float(item['qty'])
                        consumption_totals[name] = consumption_totals.get(name, 0) + qty
                elif 'items' in req:
                    parts = req['items'].split(', ')
                    for part in parts:
                        if 'x ' in part:
                            try:
                                qty_str, name = part.split('x ', 1)
                                consumption_totals[name] = consumption_totals.get(name, 0) + float(qty_str)
                            except: pass
        except ValueError: pass
        
    suggestions = []
    
    for p in products:
        name = p['name']
        total_consumed_90d = consumption_totals.get(name, 0)
        avg_monthly = total_consumed_90d / 3 # Simple 3-month average
        
        # Heuristic: Suggested Min Stock = 50% of Monthly Consumption (approx 2 weeks safety stock)
        # You can adjust this factor (e.g. 0.25 for 1 week, 1.0 for 1 month)
        suggested_min = round(avg_monthly * 0.5, 2)
        
        current_min = p.get('min_stock', 0)
        
        # Only suggest if difference is significant (e.g. > 10% change and absolute diff > 1 unit)
        diff = suggested_min - current_min
        if abs(diff) > 1 and (current_min == 0 or abs(diff) / current_min > 0.1):
            suggestions.append({
                'id': p['id'],
                'product': name,
                'current_min': current_min,
                'avg_monthly': round(avg_monthly, 2),
                'suggested_min': suggested_min,
                'diff': round(diff, 2)
            })
            
    return suggestions

def calculate_smart_stock_suggestions():
    """
    Advanced algorithm for calculating Minimum Stock based on:
    - 60 days sales history
    - Standard Deviation of demand
    - Supplier Lead Time (inferred from frequency)
    - Service Level (95% -> Z=1.645)
    
    Formula: Min Stock = (Avg Daily Demand * Lead Time) + Safety Stock
    Safety Stock = Z * StdDev_Day * sqrt(Lead Time)
    """
    import math
    import statistics
    
    requests = load_stock_requests()
    products = load_products()
    entries = load_stock_entries()
    
    # 1. Define Analysis Period (Last 60 Days)
    today = datetime.now()
    start_date = today - timedelta(days=60)
    
    # 2. Aggregate Daily Demand per Product
    # daily_demand[product_name][date_str] = qty
    daily_demand = {}
    
    # Process Requests (Internal Consumption)
    for req in requests:
        try:
            req_date = datetime.strptime(req['date'], '%d/%m/%Y')
            if req_date >= start_date:
                d_str = req['date']
                if 'items_structured' in req:
                    for item in req['items_structured']:
                        name = item['name']
                        qty = float(item.get('delivered_qty', item.get('qty', 0)))
                        if name not in daily_demand: daily_demand[name] = {}
                        daily_demand[name][d_str] = daily_demand[name].get(d_str, 0) + qty
                elif 'items' in req and isinstance(req['items'], str):
                     parts = req['items'].split(', ')
                     for part in parts:
                         if 'x ' in part:
                             try:
                                 qty_str, name = part.split('x ', 1)
                                 if name not in daily_demand: daily_demand[name] = {}
                                 daily_demand[name][d_str] = daily_demand[name].get(d_str, 0) + float(qty_str)
                             except: pass
        except: pass

    # Process Entries (Sales registered as negative entries)
    for entry in entries:
        try:
            entry_date = datetime.strptime(entry.get('date', ''), '%d/%m/%Y')
            if entry_date >= start_date:
                qty = float(entry.get('qty', 0))
                if qty < 0: # It's an outflow/sale
                    name = entry.get('product')
                    d_str = entry.get('date')
                    if name not in daily_demand: daily_demand[name] = {}
                    daily_demand[name][d_str] = daily_demand[name].get(d_str, 0) + abs(qty)
        except: pass

    suggestions = []
    
    # 3. Calculate Metrics per Product
    for p in products:
        name = p['name']
        history = daily_demand.get(name, {})
        current_min = p.get('min_stock', 0) or 0
        
        # If no history, mark as no data
        if not history:
            suggestions.append({
                'id': p['id'],
                'product': name,
                'current_min': current_min,
                'avg_monthly': 0,
                'std_dev': 0,
                'lead_time': 0,
                'suggested_min': 0,
                'raw_calculated': 0,
                'justification': "Sem histórico de movimentação recente.",
                'has_history': False
            })
            continue
            
        # Fill zero days? 
        # For accurate StdDev, we should consider days with 0 sales if the product was available.
        # Simplification: Use the 60 days period as denominator for average.
        # For StdDev, use the actual data points + zeros? 
        # Let's create a list of 60 daily values.
        
        daily_values = []
        total_qty = 0
        for i in range(60):
            d = start_date + timedelta(days=i)
            d_str = d.strftime('%d/%m/%Y')
            val = history.get(d_str, 0)
            daily_values.append(val)
            total_qty += val
            
        avg_daily = total_qty / 60
        avg_monthly = avg_daily * 30
        
        if total_qty == 0:
            continue
            
        # Standard Deviation of Daily Demand
        if len(daily_values) > 1:
            std_dev_day = statistics.stdev(daily_values)
        else:
            std_dev_day = 0
            
        # Lead Time Estimation based on Frequency
        freq = p.get('frequency', 'Semanal')
        if freq == 'Diário': lead_time = 1
        elif freq == 'Semanal': lead_time = 7
        elif freq == 'Quinzenal': lead_time = 15
        elif freq == 'Mensal': lead_time = 30
        else: lead_time = 7 # Default
        
        # Service Level 95% -> Z = 1.645
        z_score = 1.645
        
        # Safety Stock Calculation
        # Safety Stock = Z * StdDev * sqrt(Lead Time)
        safety_stock = z_score * std_dev_day * math.sqrt(lead_time)
        
        # Cycle Stock (Demand during Lead Time)
        cycle_stock = avg_daily * lead_time
        
        # Min Stock (Reorder Point)
        calculated_min = cycle_stock + safety_stock
        
        # Constraints Check (1% to 50% of Monthly Demand)
        # Note: User requested validation. 
        # "Avoid min stocks below 1% or above 50% of average monthly demand"
        # 50% of monthly demand is 15 days of stock. 
        # If lead_time is 30 days, calculated_min WILL be > 50% of monthly demand (it will be ~100% + safety).
        # So this constraint contradicts the math for long lead times.
        # I will apply the constraint but flag it in the "justification".
        
        lower_bound = avg_monthly * 0.01
        upper_bound = avg_monthly * 0.50
        
        final_suggestion = calculated_min
        notes = []
        
        if final_suggestion < lower_bound:
            final_suggestion = lower_bound
            notes.append("Ajustado p/ 1% da demanda mensal")
        elif final_suggestion > upper_bound:
            # Only cap if lead_time allows it? 
            # If lead_time > 15 days, capping at 15 days usage guarantees stockout.
            # But "User is King". I will cap and warn.
            final_suggestion = upper_bound
            notes.append("Limitado a 50% da demanda mensal (Regra de Negócio)")
            
        current_min = p.get('min_stock', 0) or 0
        
        suggestions.append({
            'id': p['id'],
            'product': name,
            'current_min': current_min,
            'avg_monthly': round(avg_monthly, 2),
            'std_dev': round(std_dev_day, 2),
            'lead_time': lead_time,
            'suggested_min': round(final_suggestion, 2),
            'raw_calculated': round(calculated_min, 2),
            'justification': f"Lead Time: {lead_time}d, Var: {round(std_dev_day, 2)}. " + "; ".join(notes),
            'has_history': True
        })
        
    return suggestions

def get_product_balances():
    products = load_products()
    entries = load_stock_entries()
    requests = load_stock_requests()
    balances = {p['name']: 0.0 for p in products}
    
    for entry in entries:
        if entry['product'] in balances:
            balances[entry['product']] += float(entry['qty'])
            
    for req in requests:
        # Only deduct stock if request is Completed (new flow) or Pending (legacy flow)
        # New flow statuses: 'Pendente Almoxarifado', 'Aguardando Confirmação' -> Do NOT deduct yet
        if req.get('status') not in ['Pendente', 'Concluído']:
            continue

        if 'items_structured' in req:
            for item in req['items_structured']:
                if item['name'] in balances:
                    # Use delivered_qty if available (partial delivery), else requested qty
                    qty = float(item.get('delivered_qty', item['qty']))
                    balances[item['name']] -= qty
        elif 'items' in req and isinstance(req['items'], str):
             parts = req['items'].split(', ')
             for part in parts:
                 try:
                     if 'x ' in part:
                         qty_str, name = part.split('x ', 1)
                         if name in balances:
                             balances[name] -= float(qty_str)
                 except ValueError:
                     pass
    return balances

def calculate_inventory(products, entries, requests, transfers, target_dept='Geral'):
    print(f"DEBUG: Calculating for {target_dept}")
    inventory = {}
    
    # 1. Helper to normalize product names for matching
    #    "Heineken long neck (BAR)" -> base: "Heineken long neck"
    def get_base_name(name):
        return name.split(' (')[0].strip()

    # 2. Define Department Aliases/Mappings
    #    Maps UI 'target_dept' to JSON 'department' values and Transfer 'to' values
    dept_map = {
        'Serviço': ['Bar', 'Serviço'],
        'Cozinha': ['Cozinha'],
        'Governança': ['Governança', 'Governanca'],
        'Manutenção': ['Manutenção', 'Manutencao'],
        'Recepção': ['Recepção', 'Recepcao'],
        'RH': ['RH'],
        'Principal': ['Principal', 'Estoques'],
        'Estoque': ['Estoque']
    }
    
    # Get valid aliases for the target department
    valid_depts = dept_map.get(target_dept, [target_dept])

    # 3. Filter Products based on View Scope
    relevant_products = []
    for p in products:
        p_name = p['name'].strip()
        p_cat = p.get('category', '').upper()
        p_dept = p.get('department', '')

        # Classification
        is_main_stock_cat = "ESTOQUE PRINCIPAL" in p_cat
        
        if target_dept == 'Geral':
            relevant_products.append(p)
            
        elif target_dept == 'Principal':
            # Show items that belong to Central Stock
            # Criteria: Explicit "ESTOQUE PRINCIPAL" category OR Dept="Estoques" or "Principal"
            if is_main_stock_cat or p_dept in ['Principal', 'Estoques']:
                relevant_products.append(p)
                
        else: # Specific Department (e.g., 'Serviço', 'Cozinha')
            # Show "Operational" items
            # Criteria: Dept matches AND NOT "Main Stock" category (unless it's the only one?)
            # User implies distinct items for Dept.
            if p_dept in valid_depts and not is_main_stock_cat:
                relevant_products.append(p)

    # Initialize Inventory
    for p in relevant_products:
        p_name = p['name'].strip()
        inventory[p_name] = {
            'balance': 0.0,
            'qty_in': 0.0,
            'qty_out': 0.0,
            'unit': p.get('unit', 'un'),
            'price': p.get('price', 0.0)
        }

    # 4. Calculate Flow
    for p_name in inventory:
        base_name = get_base_name(p_name)
        
        # --- ENTRIES (Purchases / Reset) ---
        for entry in entries:
            entry_prod = entry['product'].strip()
            # Strict match for Purchases (usually bought with specific name)
            if entry_prod == p_name:
                try:
                    qty = float(entry['qty'])
                    if qty >= 0:
                        inventory[p_name]['qty_in'] += qty
                    else:
                        # Negative entry (Sale/Consumption/Adjustment)
                        inventory[p_name]['qty_out'] += abs(qty)
                except ValueError:
                    pass
            # Note: We don't use base_name here because if you buy "Heineken", 
            # it goes to "Heineken" (Main), not "Heineken (BAR)".

        # --- TRANSFERS ---
        for t in transfers:
            t_prod = t['product'].strip()
            t_qty = float(t['qty'])
            t_from = t['from']
            t_to = t['to']
            
            # INCOMING (To this context)
            # Only relevant if we are not in 'Geral' (Geral shows global sum, transfers cancel out or just move?)
            # Actually, for 'Geral', Balance = Total In - Total Out. Internal transfers shouldn't change Total Balance?
            # User said "Inventário Geral... procurar produtos".
            # If 'Geral', we might just sum everything. 
            # But let's follow the standard logic:
            
            # Check if Transfer Destination matches our Target Dept
            is_incoming = False
            if target_dept == 'Geral':
                pass # Internal transfers don't increase Global Stock (unless from external?)
            elif target_dept == 'Principal':
                if t_to == 'Principal': is_incoming = True
            else:
                if t_to in valid_depts: is_incoming = True
            
            if is_incoming:
                # Match Product
                # 1. Exact Match
                if t_prod == p_name:
                    inventory[p_name]['qty_in'] += t_qty
                # 2. Base Name Match (Main -> Dept)
                #    Only if we are in a Dept View (not Principal/Geral usually)
                elif target_dept not in ['Geral', 'Principal'] and t_prod == base_name:
                     inventory[p_name]['qty_in'] += t_qty

            # OUTGOING (From this context)
            is_outgoing = False
            if target_dept == 'Geral':
                pass # Internal transfers don't decrease Global Stock
            elif target_dept == 'Principal':
                if t_from == 'Principal': is_outgoing = True
            else:
                if t_from in valid_depts: is_outgoing = True
                
            if is_outgoing:
                # For Outgoing, usually the product name matches exactly what we have
                if t_prod == p_name:
                    inventory[p_name]['qty_out'] += t_qty
                # (Rare case: Transfer out "Base Name" but we hold "Variant"? Unlikely logic.)

        # --- CONSUMPTION / REQUESTS (Sales) ---
        # Logic: Requests are usually for "USO INTERNO" or Sales
        for req in requests:
            if 'items_structured' in req:
                for item in req['items_structured']:
                    # Filter by "Destination Stock" (e.g., USO INTERNO)
                    # And ensure it CAME FROM our department
                    
                    # Note: stock_requests.json doesn't always have 'source_dept'.
                    # But if we are in 'Bar', and we sell 'Heineken (BAR)', it's an Out.
                    
                    req_prod = item['name'].strip()
                    req_qty = float(item.get('delivered_qty', 0)) or float(item.get('qty', 0))
                    
                    if req_prod == p_name:
                        # If the product name matches EXACTLY, it belongs to this inventory item.
                        # So it's an OUT.
                        inventory[p_name]['qty_out'] += req_qty

    # Calculate Balance
    for name, data in inventory.items():
        data['balance'] = data['qty_in'] - data['qty_out']
        # Add total value
        data['total_value'] = data['balance'] * data['price']
        
    return inventory
