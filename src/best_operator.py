"""Composite "best operator at this address" ranking — pure logic.

Sits on top of the operators[] produced by coverage_verdict.signal_verdict.
Scores each operator from three signals: signal_tier (distance band),
real_5g availability (3.5 GHz n78 C-band) and technology depth (5G/LTE/...
present), flags the single winner as `recommended`, and attaches a PL/EN
rationale string. No Flask imports here so the ranking is unit-testable in
isolation.

REFERRAL_LINKS is the monetization map (operator slug -> affiliate URL +
UTM/subid); build_referral_url() assembles the outbound link the
/go/operator/<slug> redirect 302s to.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from coverage_verdict import TIER_LABELS_PL


OPERATOR_SLUGS = {
    'Play': 'play',
    'Orange': 'orange',
    'Plus': 'plus',
    'T-Mobile': 'tmobile',
}

TIER_SCORES = {'Excellent': 40, 'Good': 30, 'Fair': 20, 'Poor': 10}
REAL_5G_BONUS = 25
TECH_SCORES = {'5G': 12, 'LTE': 8, '3G': 3, 'GSM': 2}

_UTM = {
    'utm_source': 'signal-scout',
    'utm_medium': 'referral',
    'utm_campaign': 'best-operator',
}

_DEFAULT_REFERRAL_LINKS = {
    'orange': {'url': 'https://www.orange.pl/sklep/oferta-internetowa', 'subid': 'ss-orange'},
    'play': {'url': 'https://www.play.pl', 'subid': 'ss-play'},
    'plus': {'url': 'https://www.plus.pl', 'subid': 'ss-plus'},
    'tmobile': {'url': 'https://www.t-mobile.pl/c/internet-mobilny', 'subid': 'ss-tmobile'},
}


def _load_referral_links():
    raw = os.getenv('REFERRAL_LINKS_JSON', '').strip()
    if not raw:
        return dict(_DEFAULT_REFERRAL_LINKS)
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return dict(_DEFAULT_REFERRAL_LINKS)
    links = dict(_DEFAULT_REFERRAL_LINKS)
    if isinstance(parsed, dict):
        for slug, entry in parsed.items():
            if isinstance(entry, str):
                links[slug] = {'url': entry, 'subid': f'ss-{slug}'}
            elif isinstance(entry, dict) and entry.get('url'):
                links[slug] = {'url': entry['url'], 'subid': entry.get('subid') or f'ss-{slug}'}
    return links


REFERRAL_LINKS = _load_referral_links()


def operator_slug(name):
    if not name:
        return ''
    mapped = OPERATOR_SLUGS.get(name)
    if mapped:
        return mapped
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def has_referral(slug):
    return slug in REFERRAL_LINKS


def build_referral_url(slug):
    entry = REFERRAL_LINKS.get(slug)
    if not entry:
        return None
    url = entry['url'] if isinstance(entry, dict) else entry
    subid = entry.get('subid') if isinstance(entry, dict) else None
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(_UTM)
    if subid:
        params['utm_content'] = subid
        params['subid'] = subid
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(params), parts.fragment))


def _extract_operators(verdict):
    if isinstance(verdict, dict):
        return list(verdict.get('operators') or [])
    if isinstance(verdict, (list, tuple)):
        return list(verdict)
    return []


def _score(op):
    score = TIER_SCORES.get(op.get('signal_tier'), 0)
    if op.get('real_5g'):
        score += REAL_5G_BONUS
    techs = op.get('technologies') or {}
    for tech, present in techs.items():
        if present:
            score += TECH_SCORES.get(tech, 0)
    return score


def _distance_key(op):
    dist = op.get('nearest_distance_km')
    return dist if isinstance(dist, (int, float)) else float('inf')


def _fmt_km(km):
    return f'{round(km * 1000)} m' if km < 1 else f'{km:.1f} km'


def _fiveg_phrase(op):
    techs = op.get('technologies') or {}
    if op.get('real_5g'):
        r_km = op.get('real5g_km')
        n_km = op.get('nearest_distance_km')
        # When the 3.5 GHz mast is NOT the nearest one, name its distance so the
        # badge/copy can't be misread as "the nearest mast is real 5G".
        if (isinstance(r_km, (int, float)) and isinstance(n_km, (int, float))
                and r_km > n_km):
            km = _fmt_km(r_km)
            return (f'real 5G (3.5 GHz) {km} away', f'prawdziwe 5G (3,5 GHz) {km} stąd')
        return ('real 5G (3.5 GHz)', 'prawdziwe 5G (3,5 GHz)')
    if techs.get('5G'):
        return ('5G coverage', 'zasięg 5G')
    if techs.get('LTE'):
        return ('LTE coverage', 'zasięg LTE')
    return ('basic coverage', 'podstawowy zasięg')


def build_rationale(op, recommended):
    tier = op.get('signal_tier')
    tier_en = tier or 'No'
    tier_pl = TIER_LABELS_PL.get(tier, 'Brak')
    fg_en, fg_pl = _fiveg_phrase(op)
    techs = op.get('technologies') or {}
    if recommended:
        r_km = op.get('real5g_km')
        n_km = op.get('nearest_distance_km')
        n78_is_nearest = (
            isinstance(r_km, (int, float)) and isinstance(n_km, (int, float))
            and r_km <= n_km
        )
        if op.get('real_5g') and n78_is_nearest:
            core_en = f'nearest 5G mast + {fg_en}'
            core_pl = f'najbliższy maszt 5G + {fg_pl}'
        elif op.get('real_5g') or techs.get('5G'):
            core_en = f'nearest mast + {fg_en}'
            core_pl = f'najbliższy maszt + {fg_pl}'
        else:
            core_en = f'nearest mast + {tier_en.lower()} signal'
            core_pl = f'najbliższy maszt + {tier_pl.lower()} sygnał'
        return {
            'en': f'Best for you: {core_en}',
            'pl': f'Najlepszy dla Ciebie: {core_pl}',
        }
    return {
        'en': f'{tier_en} signal · {fg_en}',
        'pl': f'{tier_pl} sygnał · {fg_pl}',
    }


def rank_operators(verdict):
    operators = _extract_operators(verdict)
    ranked = []
    for op in operators:
        ranked.append({
            **op,
            'slug': operator_slug(op.get('operator')),
            'rank_score': _score(op),
        })
    ranked.sort(key=lambda o: (-o['rank_score'], _distance_key(o), o.get('operator') or ''))
    for index, op in enumerate(ranked):
        op['recommended'] = index == 0
        op['rationale'] = build_rationale(op, op['recommended'])
    return ranked
