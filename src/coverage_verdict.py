import re

FREQUENCY_RANGES = {
    'high': [200, 500, 1000, 1500],
    'mid': [300, 750, 1500, 2000],
    'low': [500, 1500, 3000, 5000],
}

DEFAULT_BAND = 'low'

REAL_5G_MIN_MHZ = 3400

PROVIDER_SHORT = {
    'P4 sp. z o.o.': 'Play',
    'Orange Polska S.A.': 'Orange',
    'T-Mobile Polska S.A.': 'T-Mobile',
    'Polkomtel sp. z o.o.': 'Plus',
}

TIER_LABELS_PL = {
    'Poor': 'Niski',
    'Fair': 'Średni',
    'Good': 'Dobry',
    'Excellent': 'Bardzo dobry',
}

_SCORE_ANCHORS = [100.0, 75.0, 50.0, 25.0, 0.0]

_FIVE_G_RE = re.compile(r'^5G(\d+)')


def parse_5g_mhz(band):
    match = _FIVE_G_RE.match(str(band).upper().strip())
    return int(match.group(1)) if match else None


def _technology_for_band(band):
    label = str(band).upper().strip()
    if label.startswith('5G'):
        return '5G'
    if label.startswith('L'):
        return 'LTE'
    if label.startswith('UMTS') or label.startswith('3G'):
        return '3G'
    if label.startswith('GSM'):
        return 'GSM'
    return None


def _coerce_distance(value):
    return value if isinstance(value, (int, float)) else float('inf')


def _tier_for_distance(distance_km, thresholds):
    meters = distance_km * 1000
    if meters <= thresholds[0]:
        return 'Excellent'
    if meters <= thresholds[1]:
        return 'Good'
    if meters <= thresholds[2]:
        return 'Fair'
    return 'Poor'


def _score_for_distance(distance_km, thresholds):
    meters = distance_km * 1000
    breakpoints = [0.0] + [float(t) for t in thresholds]
    if meters <= 0:
        return 100
    if meters >= breakpoints[-1]:
        return 0
    for i in range(1, len(breakpoints)):
        if meters <= breakpoints[i]:
            lo_d, hi_d = breakpoints[i - 1], breakpoints[i]
            lo_s, hi_s = _SCORE_ANCHORS[i - 1], _SCORE_ANCHORS[i]
            span = hi_d - lo_d
            frac = (meters - lo_d) / span if span else 0.0
            return int(round(lo_s + (hi_s - lo_s) * frac))
    return 0


def _build_labels(signal_tier, has_5g, real_5g):
    if signal_tier is None:
        return {
            'pl': {
                'signal_tier': 'Brak zasięgu',
                'real_5g': 'Brak 5G',
                'headline': 'Brak zasięgu w pobliżu',
            },
            'en': {
                'signal_tier': 'No coverage',
                'real_5g': 'No 5G',
                'headline': 'No coverage nearby',
            },
        }
    tier_pl = TIER_LABELS_PL[signal_tier]
    if real_5g:
        five_pl, five_en = 'Prawdziwe 5G (3,5 GHz)', 'Real 5G (3.5 GHz)'
        head_pl = f'{tier_pl} zasięg · {five_pl} dostępne'
        head_en = f'{signal_tier} coverage · {five_en} available'
    elif has_5g:
        five_pl, five_en = 'Tylko 5G zasięgowe', 'Coverage 5G only'
        head_pl = f'{tier_pl} zasięg · {five_pl}'
        head_en = f'{signal_tier} coverage · {five_en}'
    else:
        five_pl, five_en = 'Brak 5G', 'No 5G'
        head_pl = f'{tier_pl} zasięg · {five_pl}'
        head_en = f'{signal_tier} coverage · {five_en}'
    return {
        'pl': {'signal_tier': tier_pl, 'real_5g': five_pl, 'headline': head_pl},
        'en': {'signal_tier': signal_tier, 'real_5g': five_en, 'headline': head_en},
    }


def _no_coverage(band):
    return {
        'signal_tier': None,
        'signal_score': 0,
        'nearest_mast_km': None,
        'nearest_operator': None,
        'has_5g': False,
        'real_5g': False,
        'band': band,
        'operators': [],
        'labels': _build_labels(None, False, False),
    }


def signal_verdict(stations, band='low'):
    band = band if band in FREQUENCY_RANGES else DEFAULT_BAND
    thresholds = FREQUENCY_RANGES[band]

    if not stations:
        return _no_coverage(band)

    by_provider = {}
    for st in stations:
        provider = st.get('service_provider')
        distance = st.get('distance')
        entry = by_provider.get(provider)
        if entry is None:
            entry = by_provider[provider] = {
                'service_provider': provider,
                'nearest_distance_km': None,
                'technologies': {'5G': False, 'LTE': False, '3G': False, 'GSM': False},
                'mhz_5g': set(),
            }
        if isinstance(distance, (int, float)) and (
            entry['nearest_distance_km'] is None or distance < entry['nearest_distance_km']
        ):
            entry['nearest_distance_km'] = distance
        for label in (st.get('frequency_bands') or []):
            tech = _technology_for_band(label)
            if tech is not None:
                entry['technologies'][tech] = True
            mhz = parse_5g_mhz(label)
            if mhz is not None:
                entry['mhz_5g'].add(mhz)

    operators = []
    for entry in by_provider.values():
        op_distance = entry['nearest_distance_km']
        mhz_list = sorted(entry['mhz_5g'], reverse=True)
        operators.append({
            'operator': PROVIDER_SHORT.get(entry['service_provider'], entry['service_provider']),
            'service_provider': entry['service_provider'],
            'nearest_distance_km': round(op_distance, 2) if op_distance is not None else None,
            'signal_tier': _tier_for_distance(op_distance, thresholds) if op_distance is not None else None,
            'technologies': entry['technologies'],
            'real_5g': any(m >= REAL_5G_MIN_MHZ for m in mhz_list),
            '5g_bands_mhz': mhz_list,
        })
    operators.sort(key=lambda o: (o['nearest_distance_km'] is None, o['nearest_distance_km'] or 0.0))

    nearest = min(stations, key=lambda st: _coerce_distance(st.get('distance')))
    nearest_distance = _coerce_distance(nearest.get('distance'))
    if nearest_distance == float('inf'):
        return _no_coverage(band)

    signal_tier = _tier_for_distance(nearest_distance, thresholds)
    has_5g = any(op['technologies']['5G'] for op in operators)
    real_5g = any(op['real_5g'] for op in operators)

    return {
        'signal_tier': signal_tier,
        'signal_score': _score_for_distance(nearest_distance, thresholds),
        'nearest_mast_km': round(nearest_distance, 2),
        'nearest_operator': PROVIDER_SHORT.get(nearest.get('service_provider'), nearest.get('service_provider')),
        'has_5g': has_5g,
        'real_5g': real_5g,
        'band': band,
        'operators': operators,
        'labels': _build_labels(signal_tier, has_5g, real_5g),
    }
