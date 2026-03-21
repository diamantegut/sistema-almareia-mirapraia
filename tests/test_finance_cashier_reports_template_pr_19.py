from pathlib import Path


def test_finance_cashier_reports_template_has_closed_at_guard():
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "finance_cashier_reports.html"
    content = template_path.read_text(encoding="utf-8")
    assert "{% set closed_at_value = session.closed_at or '' %}" in content
    assert "|format(session.opening_balance|default(0, true))" in content
    assert "|format(t.amount|default(0, true))" in content
    assert "{{ session.closed_at.split(' ')[0] }}" not in content
    assert "|format(session.opening_balance) }}" not in content
