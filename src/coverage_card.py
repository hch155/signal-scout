from markupsafe import escape

from coverage_verdict import TIER_LABELS_PL

_DOT_CLASS = {'Orange': 'orange', 'Play': 'play', 'Plus': 'plus', 'T-Mobile': 'tmobile'}

_TIER_VISUAL = {
    'Excellent': ('#16a34a', 4),
    'Good': ('#facc15', 3),
    'Fair': ('#f97316', 2),
    'Poor': ('#dc2626', 1),
}

_REAL_5G_MIN_MHZ = 3400

_CARD_CSS = (
    ":root{color-scheme:light dark}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:#f1f5f9;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#0f172a}"
    ".cc-card{max-width:480px;margin:16px auto;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px 18px 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}"
    ".cc-addr{font-size:13px;font-weight:600;color:#0f172a;line-height:1.3}"
    ".cc-sub{font-size:11px;color:#64748b;margin-top:2px}"
    ".cc-verdict{display:flex;align-items:center;gap:12px;margin-top:14px}"
    ".cc-bars{display:flex;align-items:flex-end;gap:3px;height:28px;flex:none}"
    ".cc-bar{width:6px;border-radius:2px;background:currentColor;opacity:.22}"
    ".cc-bar.on{opacity:1}"
    ".cc-bar:nth-child(1){height:11px}.cc-bar:nth-child(2){height:17px}.cc-bar:nth-child(3){height:23px}.cc-bar:nth-child(4){height:28px}"
    ".cc-tier{font-size:24px;font-weight:800;line-height:1.05}"
    ".cc-tier-sub{font-size:12px;color:#64748b;margin-top:2px}"
    ".cc-badges{margin-top:12px;display:flex;flex-wrap:wrap;gap:6px}"
    ".cc-badge{font-size:11px;font-weight:600;padding:3px 9px;border-radius:999px;white-space:nowrap}"
    ".cc-badge.g{background:#dcfce7;color:#166534}.cc-badge.a{background:#fef3c7;color:#92400e}.cc-badge.n{background:#f1f5f9;color:#475569}"
    ".cc-ops{margin-top:14px;border-top:1px solid #e2e8f0;padding-top:10px;display:flex;flex-direction:column;gap:8px}"
    ".cc-op{display:flex;align-items:center;gap:8px;font-size:13px}"
    ".cc-dot{width:10px;height:10px;border-radius:999px;flex:none;box-shadow:0 0 0 1px rgba(0,0,0,.06)}"
    ".cc-dot.orange{background:#fb923c}.cc-dot.play{background:#a78bfa}.cc-dot.plus{background:#22c55e}.cc-dot.tmobile{background:#f87171}.cc-dot.unknown{background:#94a3b8}"
    ".cc-op-name{font-weight:600;min-width:62px}"
    ".cc-op-dist{color:#475569;font-variant-numeric:tabular-nums}"
    ".cc-op-tier{font-size:11px;font-weight:700}"
    ".cc-op-bands{margin-left:auto;display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}"
    ".cc-chip{font-size:10px;font-weight:600;padding:2px 6px;border-radius:6px;background:#f1f5f9;color:#475569;white-space:nowrap}"
    ".cc-chip.g{background:#dcfce7;color:#166534}"
    ".cc-foot{margin-top:12px;border-top:1px solid #e2e8f0;padding-top:9px}"
    ".cc-disc{font-size:10px;color:#94a3b8;line-height:1.45}"
    ".cc-meta{font-size:10px;color:#94a3b8;margin-top:6px;display:flex;justify-content:space-between;gap:8px}"
    ".cc-meta a{color:#2563eb;text-decoration:none}"
    "@media (prefers-color-scheme:dark){"
    "body{background:#0b1220;color:#e5e7eb}"
    ".cc-card{background:#111827;border-color:#1f2937;box-shadow:0 1px 3px rgba(0,0,0,.5)}"
    ".cc-addr{color:#f3f4f6}.cc-sub,.cc-tier-sub,.cc-op-dist{color:#9ca3af}"
    ".cc-ops,.cc-foot{border-color:#1f2937}"
    ".cc-badge.g{background:rgba(22,163,74,.18);color:#86efac}.cc-badge.a{background:rgba(245,158,11,.18);color:#fcd34d}.cc-badge.n{background:#1f2937;color:#cbd5e1}"
    ".cc-chip{background:#1f2937;color:#cbd5e1}.cc-chip.g{background:rgba(22,163,74,.18);color:#86efac}"
    ".cc-dot.orange{background:#fdba74}.cc-dot.play{background:#c4b5fd}.cc-dot.plus{background:#4ade80}.cc-dot.tmobile{background:#fca5a5}"
    ".cc-disc,.cc-meta{color:#6b7280}.cc-meta a{color:#60a5fa}"
    "}"
)


def _format_distance_km(km):
    if km is None:
        return '—'
    return f"{round(km * 1000)} m" if km < 1 else f"{km:.1f} km"


def _signal_bars(active, color):
    cells = ''.join(
        f'<span class="cc-bar{" on" if i <= active else ""}"></span>'
        for i in range(1, 5)
    )
    return f'<span class="cc-bars" style="color:{color}">{cells}</span>'


def _document(title, body):
    return (
        '<!DOCTYPE html><html lang="pl"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f'<title>{title}</title>'
        f'<style>{_CARD_CSS}</style>'
        f'</head><body>{body}</body></html>'
    )


def _operator_bands(op):
    bands = op.get('5g_bands_mhz') or []
    if bands:
        return ''.join(
            f'<span class="cc-chip{" g" if mhz >= _REAL_5G_MIN_MHZ else ""}">{int(mhz)} MHz</span>'
            for mhz in bands
        )
    techs = op.get('technologies') or {}
    for tech in ('LTE', '3G', 'GSM'):
        if techs.get(tech):
            return f'<span class="cc-chip">{escape(tech)}</span>'
    return ''


def _operator_row(op):
    name = op.get('operator') or '—'
    dot = _DOT_CLASS.get(name, 'unknown')
    tier = op.get('signal_tier')
    color, _bars = _TIER_VISUAL.get(tier, ('#94a3b8', 0))
    tier_pl = TIER_LABELS_PL.get(tier, 'Brak') if tier else 'Brak'
    return (
        '<div class="cc-op">'
        f'<span class="cc-dot {dot}"></span>'
        f'<span class="cc-op-name">{escape(name)}</span>'
        f'<span class="cc-op-dist">{escape(_format_distance_km(op.get("nearest_distance_km")))}</span>'
        f'<span class="cc-op-tier" style="color:{color}">{escape(tier_pl)}</span>'
        f'<span class="cc-op-bands">{_operator_bands(op)}</span>'
        '</div>'
    )


def _real_5g_badge(coverage, has_5g):
    if coverage.get('real_5g'):
        cls, text = 'g', 'Prawdziwe 5G (3,5 GHz)'
    elif has_5g:
        cls, text = 'a', 'Tylko 5G zasięgowe'
    else:
        cls, text = 'n', 'Brak 5G'
    return f'<span class="cc-badge {cls}">{escape(text)}</span>'


def _disclaimer(disclaimer, data_date):
    return (
        '<div class="cc-foot">'
        f'<div class="cc-disc">{escape(disclaimer)}</div>'
        '<div class="cc-meta">'
        f'<span>Dane UKE: {escape(data_date or "—")}</span>'
        '<a href="https://signal-scout.com/" target="_blank" rel="noopener">Signal-Scout</a>'
        '</div></div>'
    )


def render_message(title, message, disclaimer=None, data_date=None):
    body = (
        '<div class="cc-card">'
        f'<div class="cc-addr">{escape(title)}</div>'
        f'<div class="cc-verdict"><span class="cc-tier" style="color:#64748b">{escape(message)}</span></div>'
        + (_disclaimer(disclaimer, data_date) if disclaimer is not None else '')
        + '</div>'
    )
    return _document(escape(title), body)


def render_coverage_card(payload):
    status = payload.get('status')
    query = payload.get('query') or ''
    data_date = payload.get('data_date')
    disclaimer = payload.get('disclaimer')
    if isinstance(disclaimer, dict):
        disclaimer = disclaimer.get('pl', '')

    if status == 'no_match':
        return render_message('Zasięg sieci', 'Nie znaleziono adresu', disclaimer, data_date)

    match = payload.get('match') or {}
    display = match.get('display') or query

    if status == 'outside_pl':
        return render_message(f'Zasięg sieci — {display}'[:80], 'Poza obszarem Polski',
                              disclaimer, data_date)

    coverage = payload.get('coverage') or {}
    labels = payload.get('labels') or {}
    operators = coverage.get('operators') or []
    tier = coverage.get('signal_tier')
    color, bars = _TIER_VISUAL.get(tier, ('#94a3b8', 0))
    tier_pl = labels.get('tier_pl') or 'Brak zasięgu'
    has_5g = any((op.get('technologies') or {}).get('5G') for op in operators)

    nearest = operators[0] if operators else {}
    sub_bits = []
    if nearest:
        sub_bits.append(
            f"Najbliższy nadajnik: {_format_distance_km(nearest.get('nearest_distance_km'))}"
            f" ({nearest.get('operator') or '—'})"
        )
    if payload.get('is_estimate'):
        sub_bits.append('pozycja przybliżona (środek ulicy)')
    subline = ' · '.join(sub_bits)

    ops_html = ''.join(_operator_row(op) for op in operators)

    body = (
        '<div class="cc-card">'
        f'<div class="cc-addr">{escape(display)}</div>'
        + (f'<div class="cc-sub">{escape(subline)}</div>' if subline else '')
        + '<div class="cc-verdict">'
        + _signal_bars(bars, color)
        + '<div>'
        f'<div class="cc-tier" style="color:{color}">{escape(tier_pl)}</div>'
        f'<div class="cc-tier-sub">{escape(labels.get("headline_pl") or "")}</div>'
        '</div></div>'
        f'<div class="cc-badges">{_real_5g_badge(coverage, has_5g)}</div>'
        + (f'<div class="cc-ops">{ops_html}</div>' if ops_html else '')
        + _disclaimer(disclaimer, data_date)
        + '</div>'
    )
    return _document(escape(f'Zasięg sieci — {display}'), body)
