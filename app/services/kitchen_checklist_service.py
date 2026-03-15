import json
import os
import uuid
from collections import Counter
from datetime import datetime
from app.services.data_service import load_products
from app.services.logger_service import LoggerService

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
KITCHEN_CHECKLISTS_FILE = os.path.join(DATA_DIR, 'kitchen_checklists.json')


class KitchenChecklistService:
    LIST_TYPES = {'conferencia', 'compras', 'limpeza'}
    ITEM_STATUSES = {'ok', 'faltando', 'baixo_estoque', 'vencido', 'comprar'}
    PURCHASE_TRIGGER_STATUSES = {'faltando', 'baixo_estoque', 'comprar'}
    PERIODICITIES = {'diaria', 'semanal', 'quinzenal', 'mensal', 'sob_demanda'}

    @staticmethod
    def _now_iso():
        return datetime.now().isoformat()

    @staticmethod
    def _now_br():
        return datetime.now().strftime('%d/%m/%Y %H:%M')

    @staticmethod
    def _ensure_data_dir():
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

    @staticmethod
    def _default_templates():
        now = KitchenChecklistService._now_iso()
        rows = [
            ('Abertura da cozinha', 'conferencia'),
            ('Fechamento da cozinha', 'conferencia'),
            ('Compras diárias', 'compras'),
            ('Hortifruti', 'compras'),
            ('Açougue', 'compras'),
            ('Limpeza', 'limpeza'),
        ]
        return [
            {
                'id': str(uuid.uuid4()),
                'name': name,
                'list_type': list_type,
                'items': [],
                'created_at': now,
                'updated_at': now,
                'is_default': True,
            }
            for name, list_type in rows
        ]

    @staticmethod
    def _default_state():
        return {
            'version': 2,
            'lists': [],
            'templates': KitchenChecklistService._default_templates(),
            'executions': [],
            'shopping_lists': [],
            'history': [],
        }

    @staticmethod
    def _load_raw():
        KitchenChecklistService._ensure_data_dir()
        if not os.path.exists(KITCHEN_CHECKLISTS_FILE):
            return KitchenChecklistService._default_state()
        try:
            with open(KITCHEN_CHECKLISTS_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return KitchenChecklistService._default_state()
        if isinstance(payload, list):
            now = KitchenChecklistService._now_iso()
            migrated = []
            for row in payload:
                row_type = row.get('type')
                mapped_type = 'compras' if row_type == 'quantity' else 'conferencia'
                items = KitchenChecklistService._normalize_items(row.get('items') or [])
                migrated.append({
                    'id': row.get('id') or str(uuid.uuid4()),
                    'name': row.get('name') or 'Lista sem nome',
                    'list_type': mapped_type,
                    'base_template_id': None,
                    'responsible': row.get('responsible') or '',
                    'periodicity': row.get('periodicity') or 'sob_demanda',
                    'items': items,
                    'status': row.get('status') or 'ativa',
                    'created_by': row.get('created_by') or 'Sistema',
                    'created_at': row.get('created_at') or now,
                    'updated_at': row.get('updated_at') or row.get('created_at') or now,
                })
            return {
                'version': 2,
                'lists': migrated,
                'templates': KitchenChecklistService._default_templates(),
                'executions': [],
                'shopping_lists': [],
                'history': [],
            }
        state = KitchenChecklistService._default_state()
        state.update(payload if isinstance(payload, dict) else {})
        state['lists'] = state.get('lists') or []
        state['templates'] = state.get('templates') or KitchenChecklistService._default_templates()
        state['executions'] = state.get('executions') or []
        state['shopping_lists'] = state.get('shopping_lists') or []
        state['history'] = state.get('history') or []
        return state

    @staticmethod
    def _save_raw(state):
        KitchenChecklistService._ensure_data_dir()
        with open(KITCHEN_CHECKLISTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)

    @staticmethod
    def _normalize_type(value):
        normalized = str(value or '').strip().lower()
        legacy_map = {'quantity': 'compras', 'checklist': 'conferencia'}
        normalized = legacy_map.get(normalized, normalized)
        if normalized not in KitchenChecklistService.LIST_TYPES:
            return None
        return normalized

    @staticmethod
    def _normalize_periodicity(value):
        normalized = str(value or '').strip().lower()
        if normalized not in KitchenChecklistService.PERIODICITIES:
            return 'sob_demanda'
        return normalized

    @staticmethod
    def _normalize_items(items):
        normalized = []
        for row in items or []:
            name = str(row.get('name') or '').strip()
            if not name:
                continue
            normalized.append({
                'id': str(row.get('id') or uuid.uuid4()),
                'name': name,
                'unit': str(row.get('unit') or '').strip(),
                'default_qty': str(row.get('default_qty') or row.get('qty') or '').strip(),
                'note': str(row.get('note') or '').strip(),
            })
        return normalized

    @staticmethod
    def _normalize_list_payload(payload):
        name = str((payload or {}).get('name') or '').strip()
        list_type = KitchenChecklistService._normalize_type((payload or {}).get('list_type') or (payload or {}).get('type'))
        items = KitchenChecklistService._normalize_items((payload or {}).get('items') or [])
        if not name or not list_type or not items:
            return None
        return {
            'name': name,
            'list_type': list_type,
            'base_template_id': (payload or {}).get('base_template_id') or None,
            'responsible': str((payload or {}).get('responsible') or '').strip(),
            'periodicity': KitchenChecklistService._normalize_periodicity((payload or {}).get('periodicity')),
            'items': items,
            'status': 'ativa',
        }

    @staticmethod
    def load_lists():
        state = KitchenChecklistService._load_raw()
        rows = []
        for row in state.get('lists', []):
            mapped = dict(row)
            if 'type' not in mapped:
                reverse_type = {'conferencia': 'checklist', 'compras': 'quantity', 'limpeza': 'checklist'}
                mapped['type'] = reverse_type.get(mapped.get('list_type'), 'checklist')
            rows.append(mapped)
        return rows

    @staticmethod
    def save_lists(lists):
        state = KitchenChecklistService._load_raw()
        normalized = []
        for row in lists or []:
            payload = KitchenChecklistService._normalize_list_payload({
                'name': row.get('name'),
                'list_type': row.get('list_type') or row.get('type'),
                'base_template_id': row.get('base_template_id'),
                'responsible': row.get('responsible'),
                'periodicity': row.get('periodicity'),
                'items': row.get('items') or [],
            })
            if not payload:
                continue
            now = KitchenChecklistService._now_iso()
            normalized.append({
                'id': str(row.get('id') or uuid.uuid4()),
                **payload,
                'status': row.get('status') or 'ativa',
                'created_by': row.get('created_by') or 'Sistema',
                'created_at': row.get('created_at') or now,
                'updated_at': row.get('updated_at') or now,
            })
        state['lists'] = normalized
        KitchenChecklistService._save_raw(state)

    @staticmethod
    def create_list(name, list_type, items, responsible='', periodicity='sob_demanda', base_template_id=None, user='Sistema'):
        payload = KitchenChecklistService._normalize_list_payload({
            'name': name,
            'list_type': list_type,
            'items': items,
            'responsible': responsible,
            'periodicity': periodicity,
            'base_template_id': base_template_id,
        })
        if not payload:
            return None
        state = KitchenChecklistService._load_raw()
        now = KitchenChecklistService._now_iso()
        new_list = {
            'id': str(uuid.uuid4()),
            **payload,
            'created_by': user or 'Sistema',
            'created_at': now,
            'updated_at': now,
        }
        state['lists'].append(new_list)
        KitchenChecklistService._save_raw(state)
        LoggerService.log_acao(
            acao='Criou lista de cozinha',
            entidade='Cozinha Checklist',
            detalhes={'list_id': new_list['id'], 'name': new_list['name'], 'list_type': new_list['list_type']}
        )
        return new_list

    @staticmethod
    def get_list(list_id):
        state = KitchenChecklistService._load_raw()
        return next((l for l in state.get('lists', []) if l.get('id') == list_id), None)

    @staticmethod
    def delete_list(list_id):
        state = KitchenChecklistService._load_raw()
        before = len(state.get('lists', []))
        state['lists'] = [l for l in state.get('lists', []) if l.get('id') != list_id]
        KitchenChecklistService._save_raw(state)
        removed = before != len(state['lists'])
        if removed:
            LoggerService.log_acao(
                acao='Removeu lista de cozinha',
                entidade='Cozinha Checklist',
                detalhes={'list_id': list_id}
            )
        return removed

    @staticmethod
    def update_list(list_id, data, user='Sistema'):
        payload = KitchenChecklistService._normalize_list_payload(data or {})
        if not payload:
            return None
        state = KitchenChecklistService._load_raw()
        for i, row in enumerate(state.get('lists', [])):
            if row.get('id') != list_id:
                continue
            updated = {
                **row,
                **payload,
                'updated_at': KitchenChecklistService._now_iso(),
                'updated_by': user or 'Sistema',
            }
            state['lists'][i] = updated
            KitchenChecklistService._save_raw(state)
            LoggerService.log_acao(
                acao='Atualizou lista de cozinha',
                entidade='Cozinha Checklist',
                detalhes={'list_id': list_id, 'name': updated['name'], 'list_type': updated['list_type']}
            )
            return updated
        return None

    @staticmethod
    def list_templates():
        state = KitchenChecklistService._load_raw()
        return state.get('templates', [])

    @staticmethod
    def create_template(name, list_type, items, user='Sistema'):
        list_type_normalized = KitchenChecklistService._normalize_type(list_type)
        normalized_items = KitchenChecklistService._normalize_items(items)
        template_name = str(name or '').strip()
        if not template_name or not list_type_normalized or not normalized_items:
            return None
        state = KitchenChecklistService._load_raw()
        now = KitchenChecklistService._now_iso()
        row = {
            'id': str(uuid.uuid4()),
            'name': template_name,
            'list_type': list_type_normalized,
            'items': normalized_items,
            'created_at': now,
            'updated_at': now,
            'is_default': False,
            'created_by': user or 'Sistema',
        }
        state['templates'].append(row)
        KitchenChecklistService._save_raw(state)
        LoggerService.log_acao(
            acao='Criou modelo de lista da cozinha',
            entidade='Cozinha Checklist',
            detalhes={'template_id': row['id'], 'name': row['name'], 'list_type': row['list_type']}
        )
        return row

    @staticmethod
    def update_template(template_id, data, user='Sistema'):
        state = KitchenChecklistService._load_raw()
        for index, row in enumerate(state.get('templates', [])):
            if row.get('id') != template_id:
                continue
            name = str((data or {}).get('name') or row.get('name') or '').strip()
            list_type = KitchenChecklistService._normalize_type((data or {}).get('list_type') or row.get('list_type'))
            items_payload = (data or {}).get('items')
            items = KitchenChecklistService._normalize_items(items_payload) if isinstance(items_payload, list) else row.get('items', [])
            if not name or not list_type or not items:
                return None
            updated = {
                **row,
                'name': name,
                'list_type': list_type,
                'items': items,
                'updated_at': KitchenChecklistService._now_iso(),
                'updated_by': user or 'Sistema',
            }
            state['templates'][index] = updated
            KitchenChecklistService._save_raw(state)
            LoggerService.log_acao(
                acao='Atualizou modelo de lista da cozinha',
                entidade='Cozinha Checklist',
                detalhes={'template_id': template_id, 'name': updated['name'], 'list_type': updated['list_type']}
            )
            return updated
        return None

    @staticmethod
    def delete_template(template_id):
        state = KitchenChecklistService._load_raw()
        before = len(state.get('templates', []))
        state['templates'] = [t for t in state.get('templates', []) if t.get('id') != template_id]
        KitchenChecklistService._save_raw(state)
        removed = before != len(state['templates'])
        if removed:
            LoggerService.log_acao(
                acao='Removeu modelo de lista da cozinha',
                entidade='Cozinha Checklist',
                detalhes={'template_id': template_id}
            )
        return removed

    @staticmethod
    def _parse_date(date_str):
        value = str(date_str or '').strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None

    @staticmethod
    def get_history_by_period(start_date=None, end_date=None):
        state = KitchenChecklistService._load_raw()
        start = KitchenChecklistService._parse_date(start_date)
        end = KitchenChecklistService._parse_date(end_date)
        rows = []
        for row in state.get('history', []):
            row_date = KitchenChecklistService._parse_date(row.get('date'))
            if start and (not row_date or row_date < start):
                continue
            if end and (not row_date or row_date > end):
                continue
            rows.append(row)
        return rows

    @staticmethod
    def build_period_summary(start_date=None, end_date=None):
        rows = KitchenChecklistService.get_history_by_period(start_date=start_date, end_date=end_date)
        missing_counter = Counter()
        purchased_counter = Counter()
        expired_counter = Counter()
        pending_count = 0
        completed_count = 0
        for row in rows:
            if row.get('completed_at'):
                completed_count += 1
            else:
                pending_count += 1
            for item in row.get('missing_items', []):
                missing_counter[item] += 1
            for item in row.get('sent_to_purchase', []):
                purchased_counter[item] += 1
            for item in row.get('expired_items', []):
                expired_counter[item] += 1
        return {
            'start_date': start_date,
            'end_date': end_date,
            'rows': rows,
            'pending_count': pending_count,
            'completed_count': completed_count,
            'top_missing': [{'name': k, 'count': v} for k, v in missing_counter.most_common(10)],
            'top_purchased': [{'name': k, 'count': v} for k, v in purchased_counter.most_common(10)],
            'expired_losses': [{'name': k, 'count': v} for k, v in expired_counter.most_common(10)],
        }

    @staticmethod
    def build_summary_csv(summary):
        lines = ['nome,tipo,data,criador,executor,inicio,conclusao,faltantes,vencidos,enviados_para_compra']
        for row in summary.get('rows', []):
            values = [
                str(row.get('name') or '').replace(',', ';'),
                str(row.get('list_type') or '').replace(',', ';'),
                str(row.get('date') or ''),
                str(row.get('creator') or '').replace(',', ';'),
                str(row.get('executor') or '').replace(',', ';'),
                str(row.get('started_at') or '').replace(',', ';'),
                str(row.get('completed_at') or '').replace(',', ';'),
                str(len(row.get('missing_items', []))),
                str(len(row.get('expired_items', []))),
                str(len(row.get('sent_to_purchase', []))),
            ]
            lines.append(','.join(values))
        return '\n'.join(lines)

    @staticmethod
    def duplicate_previous_shopping_list(user='Sistema'):
        state = KitchenChecklistService._load_raw()
        rows = [row for row in state.get('shopping_lists', []) if row.get('status') == 'concluida']
        if not rows:
            return None
        source = sorted(rows, key=lambda x: x.get('completed_at') or x.get('created_at') or '')[-1]
        copied_items = []
        for item in source.get('items', []):
            copied_items.append({
                'id': str(uuid.uuid4()),
                'name': item.get('name', ''),
                'quantity': item.get('quantity', ''),
                'unit': item.get('unit', ''),
                'observation': item.get('observation', ''),
            })
        return KitchenChecklistService.create_shopping_list(
            name=f"{source.get('name', 'Compras')} (duplicada)",
            items=copied_items,
            observation=source.get('observation', ''),
            source='duplicada',
            user=user,
        )

    @staticmethod
    def create_shopping_list(name, items, observation='', source='manual', base_template_id=None, user='Sistema'):
        clean_name = str(name or '').strip()
        clean_items = []
        for item in items or []:
            item_name = str(item.get('name') or '').strip()
            if not item_name:
                continue
            clean_items.append({
                'id': str(item.get('id') or uuid.uuid4()),
                'name': item_name,
                'quantity': str(item.get('quantity') or '').strip(),
                'unit': str(item.get('unit') or '').strip(),
                'observation': str(item.get('observation') or '').strip(),
            })
        if not clean_name or not clean_items:
            return None
        state = KitchenChecklistService._load_raw()
        now = KitchenChecklistService._now_iso()
        row = {
            'id': str(uuid.uuid4()),
            'name': clean_name,
            'list_type': 'compras',
            'status': 'concluida',
            'source': source,
            'base_template_id': base_template_id,
            'items': clean_items,
            'observation': str(observation or '').strip(),
            'created_at': now,
            'completed_at': now,
            'created_by': user or 'Sistema',
            'executor': user or 'Sistema',
        }
        state['shopping_lists'].append(row)
        history_row = {
            'id': str(uuid.uuid4()),
            'name': row['name'],
            'list_type': 'compras',
            'date': now[:10],
            'creator': row['created_by'],
            'executor': row['executor'],
            'started_at': row['created_at'],
            'completed_at': row['completed_at'],
            'missing_items': [],
            'expired_items': [],
            'sent_to_purchase': [i['name'] for i in clean_items],
            'source_id': row['id'],
            'source_kind': 'shopping_list',
        }
        state['history'].append(history_row)
        KitchenChecklistService._save_raw(state)
        LoggerService.log_acao(
            acao='Concluiu lista de compras da cozinha',
            entidade='Cozinha Checklist',
            detalhes={'shopping_list_id': row['id'], 'name': row['name'], 'items': len(row['items'])}
        )
        return row

    @staticmethod
    def start_execution(list_id, user='Sistema'):
        state = KitchenChecklistService._load_raw()
        source_list = next((l for l in state.get('lists', []) if l.get('id') == list_id), None)
        if not source_list:
            return None
        now = KitchenChecklistService._now_iso()
        execution = {
            'id': str(uuid.uuid4()),
            'list_id': source_list['id'],
            'name': source_list['name'],
            'list_type': source_list.get('list_type'),
            'creator': source_list.get('created_by', 'Sistema'),
            'executor': user or 'Sistema',
            'started_at': now,
            'completed_at': None,
            'status': 'em_execucao',
            'items': [
                {
                    'id': item.get('id') or str(uuid.uuid4()),
                    'name': item.get('name') or '',
                    'unit': item.get('unit') or '',
                    'default_qty': item.get('default_qty') or '',
                    'status': 'ok',
                    'observation': '',
                }
                for item in source_list.get('items', [])
            ],
        }
        state['executions'].append(execution)
        KitchenChecklistService._save_raw(state)
        LoggerService.log_acao(
            acao='Iniciou execução de lista da cozinha',
            entidade='Cozinha Checklist',
            detalhes={'execution_id': execution['id'], 'list_id': list_id}
        )
        return execution

    @staticmethod
    def finish_execution(execution_id, item_results, add_to_today_purchase=False, user='Sistema'):
        state = KitchenChecklistService._load_raw()
        execution_index = None
        for idx, row in enumerate(state.get('executions', [])):
            if row.get('id') == execution_id:
                execution_index = idx
                break
        if execution_index is None:
            return None
        execution = state['executions'][execution_index]
        item_map = {str(item.get('id')): item for item in (item_results or [])}
        merged_items = []
        missing_items = []
        expired_items = []
        sent_to_purchase = []
        purchase_items = []
        for item in execution.get('items', []):
            result = item_map.get(str(item.get('id')), {})
            status = str(result.get('status') or item.get('status') or 'ok').strip().lower()
            if status not in KitchenChecklistService.ITEM_STATUSES:
                status = 'ok'
            observation = str(result.get('observation') or '').strip()
            merged = {
                **item,
                'status': status,
                'observation': observation,
            }
            merged_items.append(merged)
            if status == 'faltando':
                missing_items.append(item.get('name'))
            if status == 'vencido':
                expired_items.append(item.get('name'))
            if status in KitchenChecklistService.PURCHASE_TRIGGER_STATUSES:
                sent_to_purchase.append(item.get('name'))
                purchase_items.append({
                    'id': str(uuid.uuid4()),
                    'name': item.get('name'),
                    'quantity': '',
                    'unit': item.get('unit') or '',
                    'observation': observation,
                })
        now = KitchenChecklistService._now_iso()
        execution['items'] = merged_items
        execution['completed_at'] = now
        execution['status'] = 'concluida'
        execution['executor'] = user or execution.get('executor') or 'Sistema'
        state['executions'][execution_index] = execution

        generated_shopping_list = None
        if add_to_today_purchase and purchase_items:
            generated_shopping_list = KitchenChecklistService.create_shopping_list(
                name=f"Compras de hoje - {datetime.now().strftime('%d/%m/%Y')}",
                items=purchase_items,
                observation='Gerada automaticamente da conferência.',
                source='checklist',
                user=user,
            )
            state = KitchenChecklistService._load_raw()

        history_row = {
            'id': str(uuid.uuid4()),
            'name': execution.get('name'),
            'list_type': execution.get('list_type'),
            'date': now[:10],
            'creator': execution.get('creator') or 'Sistema',
            'executor': execution.get('executor') or user or 'Sistema',
            'started_at': execution.get('started_at'),
            'completed_at': now,
            'missing_items': missing_items,
            'expired_items': expired_items,
            'sent_to_purchase': sent_to_purchase,
            'source_id': execution.get('id'),
            'source_kind': 'execution',
        }
        state['history'].append(history_row)
        KitchenChecklistService._save_raw(state)
        LoggerService.log_acao(
            acao='Finalizou execução de lista da cozinha',
            entidade='Cozinha Checklist',
            detalhes={
                'execution_id': execution_id,
                'missing_items': len(missing_items),
                'expired_items': len(expired_items),
                'sent_to_purchase': len(sent_to_purchase),
                'generated_shopping_list_id': generated_shopping_list.get('id') if generated_shopping_list else None,
            }
        )
        return {'execution': execution, 'history': history_row, 'generated_shopping_list': generated_shopping_list}

    @staticmethod
    def build_whatsapp_message(title, items, observation=''):
        now = datetime.now().strftime('%d/%m/%Y')
        lines = [f'{title} - {now}', '']
        for item in items or []:
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            quantity = str(item.get('quantity') or item.get('qty') or '').strip()
            unit = str(item.get('unit') or '').strip()
            status = str(item.get('status') or '').strip()
            suffix = f': {quantity} {unit}'.strip() if quantity or unit else ''
            if status:
                lines.append(f'- {name}{suffix} ({status})')
            else:
                lines.append(f'- {name}{suffix}')
        if observation:
            lines.append('')
            lines.append('Observações:')
            lines.append(f'- {observation}')
        return '\n'.join(lines)

    @staticmethod
    def get_dashboard_data():
        state = KitchenChecklistService._load_raw()
        today = datetime.now().strftime('%Y-%m-%d')
        executions_today = [row for row in state.get('executions', []) if str(row.get('started_at') or '').startswith(today)]
        pending_today = [row for row in executions_today if row.get('status') != 'concluida']
        completed_today = [row for row in executions_today if row.get('status') == 'concluida']
        history = state.get('history', [])
        missing_counter = Counter()
        purchased_counter = Counter()
        expired_counter = Counter()
        for row in history:
            for name in row.get('missing_items', []):
                missing_counter[name] += 1
            for name in row.get('sent_to_purchase', []):
                purchased_counter[name] += 1
            for name in row.get('expired_items', []):
                expired_counter[name] += 1
        return {
            'pending_today': pending_today,
            'completed_today': completed_today,
            'top_missing': [{'name': k, 'count': v} for k, v in missing_counter.most_common(5)],
            'top_purchased': [{'name': k, 'count': v} for k, v in purchased_counter.most_common(5)],
            'expired_losses': [{'name': k, 'count': v} for k, v in expired_counter.most_common(5)],
        }

    @staticmethod
    def get_overview():
        state = KitchenChecklistService._load_raw()
        dashboard = KitchenChecklistService.get_dashboard_data()
        return {
            'lists': state.get('lists', []),
            'templates': state.get('templates', []),
            'executions': state.get('executions', []),
            'shopping_lists': state.get('shopping_lists', []),
            'history': state.get('history', []),
            'dashboard': dashboard,
            'insumos': KitchenChecklistService.get_insumos(),
        }

    @staticmethod
    def get_insumos():
        products = load_products()
        return sorted([{'name': p.get('name'), 'unit': p.get('unit')} for p in products if p.get('name')], key=lambda x: x['name'])
