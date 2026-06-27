"""/rollout — Real-5G (3.5 GHz / n78) rollout tracker.

register_real5g_routes(app) wires two read endpoints:
  GET /rollout                 — current per-operator n78 site counts, MoM
                                 delta vs the previous snapshot, voivodeship
                                 breakdown, and a trend chart over snapshots.
  GET /api/v1/real5g_rollout   — the same aggregate as JSON.

Snapshot write mirrors /stats: on each render, if the UKE data date has no
snapshot yet, one is recorded (idempotent on snapshot_key). The monthly CI
job can also record it after a rebuild.
"""
from __future__ import annotations

from flask import jsonify, make_response, render_template

from queries import get_data_date
from real5g_rollout import (
    maybe_write_real5g_snapshot,
    operator_label,
    previous_real5g_snapshot,
    read_real5g_history,
    real_5g_rollout,
)

_OPERATOR_ORDER = ('Orange', 'Play', 'Plus', 'T-Mobile')


def _sqlite_path(uri: str) -> str:
    return uri.replace('sqlite:///', '', 1) if uri else ''


def register_real5g_routes(app) -> None:
    if 'rollout_page' in app.view_functions:
        return

    stations_db_path = _sqlite_path(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    users_db_path = _sqlite_path(
        (app.config.get('SQLALCHEMY_BINDS') or {}).get('users', '')
    )

    def _operator_rows(rollout: dict, previous):
        prev_ops = (previous or {}).get('by_operator') or {}
        rows = []
        for raw, count in sorted(rollout['by_operator'].items(),
                                 key=lambda kv: kv[1], reverse=True):
            prev_c = prev_ops.get(raw)
            delta = (int(count) - int(prev_c)) if isinstance(prev_c, int) else None
            rows.append({
                'raw': raw,
                'label': operator_label(raw),
                'count': int(count),
                'delta': delta,
            })
        return rows

    def _monthly_history(all_rows):
        by_month: dict = {}
        for r in sorted(all_rows, key=lambda r: r.get('snapshot_key', '')):
            month_key = (r.get('snapshot_key') or '')[:7]
            if month_key:
                by_month[month_key] = r
        history = []
        for m in sorted(by_month):
            row = by_month[m]
            ops: dict = {}
            for raw, c in (row.get('by_operator') or {}).items():
                label = operator_label(raw)
                ops[label] = ops.get(label, 0) + int(c)
            history.append({
                'month': m,
                'total': int(row.get('total_sites', 0) or 0),
                'ops': ops,
            })
        return history

    @app.route('/rollout')
    def rollout_page():
        rollout = real_5g_rollout(stations_db_path)
        last_refresh = get_data_date(stations_db_path)

        previous = None
        history_count = 0
        monthly_history: list = []
        try:
            if last_refresh != 'unknown':
                maybe_write_real5g_snapshot(users_db_path, last_refresh, rollout)
                previous = previous_real5g_snapshot(users_db_path, last_refresh)
                all_rows = read_real5g_history(users_db_path)
                history_count = len(all_rows)
                monthly_history = _monthly_history(all_rows)
        except Exception:
            app.logger.exception("real5g snapshot/read failed")

        operators = _operator_rows(rollout, previous)
        voivodeships = [
            {'name': n, 'count': int(c)}
            for n, c in sorted(rollout['by_voivodeship'].items(),
                               key=lambda kv: kv[1], reverse=True)
        ]
        total_delta = None
        if previous and isinstance(previous.get('total_sites'), int):
            total_delta = rollout['total_sites'] - int(previous['total_sites'])

        present = [o['label'] for o in operators]
        chart_operators = [op for op in _OPERATOR_ORDER if op in present]
        for o in operators:
            if o['label'] not in chart_operators:
                chart_operators.append(o['label'])

        return make_response(render_template(
            'rollout.html',
            rollout=rollout,
            operators=operators,
            voivodeships=voivodeships,
            total_delta=total_delta,
            last_refresh=last_refresh,
            history_count=history_count,
            monthly_history=monthly_history,
            chart_operators=chart_operators,
        ))

    @app.route('/api/v1/real5g_rollout')
    def api_v1_real5g_rollout():
        rollout = real_5g_rollout(stations_db_path)
        return jsonify({
            'data_date': get_data_date(stations_db_path),
            'total_sites': rollout['total_sites'],
            'by_operator': rollout['by_operator'],
            'by_voivodeship': rollout['by_voivodeship'],
        })
