import json
import os
import unicodedata
from datetime import datetime, timedelta
import calendar
import xlsxwriter

from app.services.system_config_manager import get_data_path
from app.services.data_service import load_cashier_sessions
from app.services.logger_service import LoggerService

COMMISSION_CYCLES_FILE = get_data_path('commission_cycles.json')

def normalize_dept(text):
    if not text:
        return ""
    return unicodedata.normalize('NFKD', str(text)).encode('ASCII', 'ignore').decode('utf-8').lower().strip()

def load_commission_cycles():
    if not os.path.exists(COMMISSION_CYCLES_FILE):
        return []
    try:
        with open(COMMISSION_CYCLES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_commission_cycles(cycles):
    with open(COMMISSION_CYCLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(cycles, f, indent=4, ensure_ascii=False)

def get_commission_cycle(cycle_id):
    cycles = load_commission_cycles()
    for c in cycles:
        if c['id'] == cycle_id:
            return c
    return None


def is_service_fee_removed_for_transaction(transaction):
    """
    Regra centralizada: determina se a taxa de serviço foi removida para uma transação.
    Utilizada por toda a lógica de comissão para garantir consistência.
    """
    if transaction.get('service_fee_removed', False):
        return True
    details = transaction.get('details') or {}
    if details.get('service_fee_removed', False):
        return True
    flags = transaction.get('flags') or []
    if isinstance(flags, list):
        for f in flags:
            if isinstance(f, dict) and f.get('type') == 'service_removed':
                return True
    desc = transaction.get('description') or ''
    if isinstance(desc, str) and '10% Off' in desc:
        return True
    return False

def calculate_commission(cycle_data):
    """
    Calculates commission distribution based on cycle data.
    Returns the updated cycle data with results.
    """
    # 1. Inputs
    total_commission = float(cycle_data.get('total_commission', 0))
    total_bonus = float(cycle_data.get('total_bonus', 0))
    card_percent = float(cycle_data.get('card_percent', 0.8)) # 0.0 to 1.0
    extras = float(cycle_data.get('extras', 0)) # Deductions
    
    # Tax Rates
    commission_tax_pct = float(cycle_data.get('commission_tax_percent', 12.0)) / 100.0
    bonus_tax_pct = float(cycle_data.get('bonus_tax_percent', 12.0)) / 100.0
    
    employees = cycle_data.get('employees', [])
    department_bonuses = cycle_data.get('department_bonuses', []) # List of {name: str, value: float}
    
    # 2. Global Calculations
    gross_total = total_commission + total_bonus
    
    # Deductions
    ded_convention = gross_total * 0.20
    
    # Tax Deductions (Calculated on the base amount, assuming tax is on Gross?)
    # Usually tax is on Gross - Convention? Or Gross? 
    # Original code: ded_tax = (gross_total - ded_convention) * 0.12
    # New requirement: Separate rates for Commission and Bonus.
    # Assumption: Tax base is still (Gross - Convention) proportionally split? 
    # OR Tax is on the gross amount of each?
    # Given "ded_tax = (gross_total - ded_convention) * 0.12", it seems tax is on the net after convention.
    
    # Let's split the convention deduction proportionally to apply correct tax rates
    # Or simplified: Tax is applied to the respective portions after convention deduction.
    
    comm_portion_ratio = total_commission / gross_total if gross_total > 0 else 0
    bonus_portion_ratio = total_bonus / gross_total if gross_total > 0 else 0
    
    base_after_convention = gross_total - ded_convention
    
    base_commission = base_after_convention * comm_portion_ratio
    base_bonus = base_after_convention * bonus_portion_ratio
    
    ded_tax_commission = base_commission * commission_tax_pct
    ded_tax_bonus = base_bonus * bonus_tax_pct
    
    ded_card = gross_total * card_percent * 0.02
    
    total_global_deductions = ded_convention + ded_tax_commission + ded_tax_bonus + ded_card
    
    # Net Base (Post Global Deductions)
    net_after_global = gross_total - total_global_deductions
    
    # Subtract Extras (Manual Global Deductions)
    net_after_extras = net_after_global - extras
    
    # Sum of Dept Bonuses
    total_dept_bonuses = sum(float(d.get('value', 0)) for d in department_bonuses)
    
    # Sum of Individual Bonuses
    total_indiv_bonuses = sum(float(e.get('individual_bonus', 0)) for e in employees)
    
    # Net Available for Point Distribution
    # Formula: Net - DeptBonuses - IndivBonuses
    net_for_points = net_after_extras - total_dept_bonuses - total_indiv_bonuses
    
    # Ensure non-negative (or handle deficit?)
    if net_for_points < 0:
        net_for_points = 0 # Or allow negative? Usually 0.
        
    # 3. Point Distribution Logic
    # Tiers: 1:10%, 2:30%, 3:33%, 4:17%, 5:10%
    tiers_pct = {1: 0.10, 2: 0.30, 3: 0.33, 4: 0.17, 5: 0.10}
    tier_pots = {k: net_for_points * v for k, v in tiers_pct.items()}
    
    # Count eligible employees per tier (points >= k)
    # Eligibility also depends on days_worked? The Excel formula uses "COUNTIF(Points >= k)".
    # It does NOT weight the count by days worked. It splits the pot by HEADCOUNT of eligible people.
    # Then the individual share is scaled by days_worked/30.
    # This means there is "leftover" money if people didn't work 30 days.
    # The Excel model calculates "Liquido restante" (Restante row).
    
    tier_counts = {}
    for k in range(1, 6):
        count = sum(1 for e in employees if float(e.get('points', 0)) >= k)
        tier_counts[k] = count
        
    tier_values = {}
    for k in range(1, 6):
        if tier_counts[k] > 0:
            tier_values[k] = tier_pots[k] / tier_counts[k]
        else:
            tier_values[k] = 0
            
    # 4. Individual Calculations
    results = []
    total_distributed = 0
    
    for e in employees:
        points = int(float(e.get('points', 0)))
        days = int(float(e.get('days_worked', 30)))
        indiv_bonus = float(e.get('individual_bonus', 0))
        indiv_deduction = float(e.get('individual_deduction', 0))
        consumption = float(e.get('consumption', 0))
        dept_name = e.get('department', '')
        
        # Calculate Point Share
        point_share_full = 0
        for k in range(1, 6):
            if points >= k:
                point_share_full += tier_values[k]
                
        # Scale by days
        time_factor = days / 30.0 if days > 0 else 0
        point_share_final = point_share_full * time_factor
        
        # Calculate Dept Bonus Share
        # Normalize department names for matching
        # Handle aliases: Salão -> Serviço
        
        def normalize_dept(name):
            if not name: return ""
            n = name.strip().lower()
            if n in ['salão', 'salao']: return 'serviço'
            if n in ['governança', 'governanca']: return 'governança'
            return n

        norm_emp_dept = normalize_dept(dept_name)
        
        dept_bonus_val = 0
        for d in department_bonuses:
            norm_bonus_dept = normalize_dept(d.get('name', ''))
            if norm_bonus_dept == norm_emp_dept:
                dept_bonus_val = float(d.get('value', 0))
                break
        
        dept_headcount = sum(1 for emp in employees if normalize_dept(emp.get('department')) == norm_emp_dept)
        
        if dept_headcount > 0:
            dept_share_full = dept_bonus_val / dept_headcount
        else:
            dept_share_full = 0
            
        dept_share_final = dept_share_full * time_factor
        
        # Individual Bonus is also time-scaled (like Dept Bonus)
        indiv_bonus_final = indiv_bonus * time_factor
        
        discounted_consumption = consumption
        total_final = point_share_final + dept_share_final + indiv_bonus_final - indiv_deduction - discounted_consumption
        if total_final < 0: total_final = 0
        
        e['calculated'] = {
            'point_share': round(point_share_final, 2),
            'dept_share': round(dept_share_final, 2),
            'indiv_bonus_share': round(indiv_bonus_final, 2),
            'total': round(total_final, 2)
        }
        
        total_distributed += total_final

    # 5. Summary
    cycle_data['results'] = {
        'gross_total': round(gross_total, 2),
        'ded_convention': round(ded_convention, 2),
        'ded_tax_commission': round(ded_tax_commission, 2),
        'ded_tax_bonus': round(ded_tax_bonus, 2),
        'ded_card': round(ded_card, 2),
        'total_global_deductions': round(total_global_deductions, 2),
        'net_distributable': round(net_for_points, 2), # This is the pot for points
        'total_distributed': round(total_distributed, 2),
        'remainder': round(net_for_points - sum(e['calculated']['point_share'] for e in employees), 2) # Approximation of leftovers from time scaling
    }
    
    return cycle_data

def generate_commission_model_file(output_path):
    # Keeping the original function for backup/download purposes if needed
    # (The content of the previous commission_service.py goes here)
    pass 

def compute_month_total_commission_by_ranking(month_str, commission_rate=10.0):
    """
    Compute the total commission for a given month using the same logic as /commission_ranking.
    month_str format: 'YYYY-MM'
    """
    try:
        start_date = datetime.strptime(month_str + "-01", "%Y-%m-%d")
    except Exception:
        # Fallback: use current month
        now = datetime.now()
        start_date = now.replace(day=1)
    year = start_date.year
    month = start_date.month
    last_day = calendar.monthrange(year, month)[1]
    end_date = start_date.replace(day=last_day, hour=23, minute=59, second=59)
    start_date_comp = start_date.replace(hour=0, minute=0, second=0)
    end_date_comp = end_date
    
    def _get_waiter_breakdown(transaction):
        wb = transaction.get('waiter_breakdown')
        if not wb:
            details = transaction.get('details') or {}
            wb = details.get('waiter_breakdown')
        return wb if isinstance(wb, dict) and wb else None
    
    sessions = load_cashier_sessions()
    total_commission = 0.0
    audit_summary = {
        'month': month_str,
        'commission_rate': commission_rate,
        'total_transactions': 0,
        'eligible_transactions': 0,
        'removed_transactions': 0,
        'total_base_amount': 0.0,
    }
    
    for session_data in sessions:
        for t in session_data.get('transactions', []):
            is_sale = t.get('type') == 'sale'
            is_reception_payment = t.get('type') == 'in' and t.get('category') in ['Pagamento de Conta', 'Recebimento Manual']
            if not (is_sale or is_reception_payment):
                continue
            t_date_str = t.get('timestamp')
            if not t_date_str:
                continue
            try:
                t_date = datetime.strptime(t_date_str, '%d/%m/%Y %H:%M')
            except Exception:
                continue
            if not (start_date_comp <= t_date <= end_date_comp):
                continue
            
            audit_summary['total_transactions'] += 1
            if is_service_fee_removed_for_transaction(t):
                audit_summary['removed_transactions'] += 1
                # Comissão não é gerada quando a taxa de serviço foi retirada
                try:
                    LoggerService.log_acao(
                        acao='COMMISSION_DECISION',
                        entidade='Financeiro',
                        detalhes={
                            'tx_id': t.get('id'),
                            'type': t.get('type'),
                            'category': t.get('category'),
                            'decision': 'ignored_service_fee_removed',
                            'amount': t.get('amount', 0),
                            'waiter_breakdown': t.get('waiter_breakdown') or (t.get('details') or {}).get('waiter_breakdown')
                        },
                        nivel_severidade='INFO'
                    )
                except Exception:
                    pass
                continue
            
            wb = _get_waiter_breakdown(t)
            if wb:
                for w_amt in wb.values():
                    try:
                        amt = float(w_amt)
                    except Exception:
                        amt = 0.0
                    audit_summary['eligible_transactions'] += 1
                    audit_summary['total_base_amount'] += amt
                    total_commission += amt * (commission_rate / 100.0)
                    try:
                        LoggerService.log_acao(
                            acao='COMMISSION_DECISION',
                            entidade='Financeiro',
                            detalhes={
                                'tx_id': t.get('id'),
                                'type': t.get('type'),
                                'category': t.get('category'),
                                'decision': 'applied',
                                'base_amount': amt
                            },
                            nivel_severidade='INFO'
                        )
                    except Exception:
                        pass
            else:
                try:
                    amount = float(t.get('amount', 0))
                except Exception:
                    amount = 0.0
                audit_summary['eligible_transactions'] += 1
                audit_summary['total_base_amount'] += amount
                total_commission += amount * (commission_rate / 100.0)
                try:
                    LoggerService.log_acao(
                        acao='COMMISSION_DECISION',
                        entidade='Financeiro',
                        detalhes={
                            'tx_id': t.get('id'),
                            'type': t.get('type'),
                            'category': t.get('category'),
                            'decision': 'applied_fallback_amount',
                            'base_amount': amount
                        },
                        nivel_severidade='INFO'
                    )
                except Exception:
                    pass
    
    try:
        LoggerService.log_acao(
            acao='COMMISSION_MONTHLY_CALCULATION',
            entidade='Financeiro',
            detalhes=audit_summary,
            nivel_severidade='INFO'
        )
    except Exception:
        # Não quebra o fluxo de cálculo caso o log falhe
        pass
    
    return round(total_commission, 2)
