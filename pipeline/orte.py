#!/usr/bin/env python3
"""Erlebsy: Eintritt und Öffnungszeiten von Ausflugszielen → docs/orte.json.

Quelle: Tourismus NRW e.V., Open Data Hub (eT4/destination.one). Nur Einträge
mit offener Lizenz (PD, CC0, CC BY, CC BY-SA). Übernommen werden nur Fakten:
Name, Koordinaten, Website, Preise (Erwachsene/Kind/Familie bzw. „frei“) und
die wöchentlichen Öffnungszeiten. Die Zeiten werden in die OSM-Schreibweise
(opening_hours) übersetzt, die die App schon auswertet.

Nie raten: Preise ohne klare Zuordnung (Erwachsene/Kinder/Familie) kommen nur
als Hinweistext (`preis.text`, „bitte prüfen“), nicht als Zahl.
Die App ordnet die Einträge ihren Orten zu (gleicher Name + Nähe).

Gebrauch: python3 pipeline/orte.py  (schreibt docs/orte.json)
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemeinsam as g  # noqa: E402

# Für Ausflüge uninteressant (Infrastruktur, Handel, Verwaltung).
UNWICHTIG = {
    'Mobilität', 'E-Mobilität', 'E-Bike Ladestation', 'E-Bike Verleihstation', 'Parkmöglichkeit',
    'Bushaltestelle', 'Bahnhof', 'WC-Anlage', 'Fahrradreparatur Self-Service', 'Rastplatz',
    'Einzelhandelsgeschäft/Shop', 'Hofladen', 'Souvenirs', 'Rathaus/Bürgerservice',
    'Tourist-Information', 'Infopunkt', 'Dienstleistung', 'Dienstleistungen', 'Wellness/Kosmetik',
    'Öffentliches Gebäude', 'Öffentliche Gebäude', 'Bücherei/Bibliothek', 'Schule',
    'Stadthalle/Tagungszentrum/Begegnungsstätte', 'Ort', 'Naturtafel/Infostelle',
}

_ZAHL = r'(\d{1,3}(?:[.,]\d{1,2})?)'
_EURO = rf'(?:€\s*{_ZAHL}|{_ZAHL}\s*(?:€|euro|eur\b)|:\s*{_ZAHL}\s*$)'


def _wert(m):
    for x in m.groups():
        if x:
            return float(x.replace(',', '.'))
    return None


_ERW = re.compile(r'^(eintritt\s*)?(einzelkarte\s*)?(erwachsene?r?|erw\.)\b', re.I)
_KIND = re.compile(r'^(eintritt\s*)?(einzelkarte\s*)?(kinder(\s*(und|&|/)\s*jugendliche)?|jugendliche|kind)\b', re.I)
_FAM = re.compile(r'^(eintritt\s*)?famili(en|e)(karte|ticket|tarif)?\b', re.I)
_KLEINKIND = re.compile(r'(bis|unter|bis zu|bis einschl\.?)\s*[1-6]\s*(j\b|jahr)|0\s*[-–]\s*[1-5]\s*j|'
                        r'kleinkind|baby', re.I)
_STOER = re.compile(r'ermäßig|ermässig|erm\.|gruppe|schul|student|senior|rentner|gdb|behindert|'
                    r'jahres|saison|abo|zehner|10er|abend|führung|kurs|miete|park|zzgl|teilnehmer|'
                    r'kombi|gutschein|workshop|geburtstag|gäste|karte\s*\(|%|mo\.|fr\.|sa\.|so\.|'
                    r'stunde|min\b|verleih|mitglied', re.I)
_BETRAG = re.compile(r'(?:€\s*(\d{1,3}(?:[.,]\d{1,2})?)|(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:€|euro\b|eur\b))', re.I)
_NICHT_AUSFLUG = re.compile(r'verleih|vermietung|radstation|bücherei|bibliothek|e-bike|ladestation|'
                            r'tourist|information|hotel|restaurant|café|cafe|shop|laden', re.I)


def _betraege(z):
    out = []
    for m in _BETRAG.finditer(z):
        w = float((m.group(1) or m.group(2)).replace(',', '.'))
        if 0 <= w <= 150:
            out.append(w)
    return out


def preis_aus_text(text, name=''):
    """→ dict(erw, kind, familie, frei, text, url).

    Streng (nie raten): Zahlen nur aus Zeilen, die mit „Erwachsene …“,
    „Kinder …“ bzw. „Familie …“ BEGINNEN, genau einen Betrag enthalten und
    keine Ermäßigungs-/Gruppen-/Sonderangaben. Alles andere bleibt Hinweistext.
    """
    if not text:
        return None
    t = text.strip()
    url = (re.search(r'https?://\S+', t) or [None])[0]
    if url:
        url = url.rstrip('.,);')
    erg = {'erw': None, 'kind': None, 'familie': None, 'frei': False}
    roh = [z.strip() for z in re.split(r'[\n;•|]+|,\s+(?=[A-Za-zÄÖÜäöü])', t) if z.strip()]
    zeilen = []
    for z in roh:  # „Erwachsene:“ + nächste Zeile „4 €“ zusammenführen
        if zeilen and zeilen[-1].endswith(':'):
            zeilen[-1] = f'{zeilen[-1]} {z}'
        else:
            zeilen.append(z)
    ausflug = not _NICHT_AUSFLUG.search(name)
    for z in zeilen if ausflug else []:
        if len(z) > 70 or _STOER.search(z):
            continue
        b = _betraege(z)
        frei_kind = re.search(r'\b(frei|kostenlos|kostenfrei|freier eintritt)\b', z, re.I)
        if _KIND.match(z) and not _KLEINKIND.search(z):
            if len(b) == 1:
                erg['kind'] = b[0] if erg['kind'] is None else max(erg['kind'], b[0])
            elif not b and frei_kind and erg['kind'] is None:
                erg['kind'] = 0.0
        elif _FAM.match(z) and len(b) == 1 and erg['familie'] is None:
            erg['familie'] = b[0]
        elif _ERW.match(z) and len(b) == 1 and erg['erw'] is None and b[0] > 0:
            erg['erw'] = b[0]
    # „frei“ nur bei bedingungsloser Aussage: „Freier Eintritt für Kölner am
    # KölnTag“ / „frei unter 18“ / „Mitglieder frei“ sind KEIN freier Eintritt.
    bedingt = re.search(r'\bfür\b|\bunter\b|\bbis\b|jeden|mitglied|kinder|jugend|tag\b|'
                        r'kölntag|\bam\b|\bnur\b|ermäßig|führung|außer|ausgenommen|spende|'
                        r'sonderausstellung|variier|teilweise|einige|bestimmte', t.lower())
    frei_text = None if bedingt or len(t) > 80 or not ausflug else re.search(
        r'eintritt (ist )?frei|freier eintritt|kostenfrei|kostenlos|'
        r'ohne eintritt|frei zugänglich|eintritt: ?0([.,]0+)? ?€?$', t.lower())
    if frei_text and erg['erw'] is None and erg['familie'] is None and \
            not re.search(r'[1-9]\d*(?:[.,]\d+)? ?€|€ ?[1-9]', t):
        erg['frei'] = True
    # Plausibilität: Kind teurer als Erwachsene oder Familie > 80 € → unsicher,
    # dann lieber gar keine Zahl.
    if erg['kind'] is not None and erg['erw'] is not None and erg['kind'] > erg['erw']:
        erg['kind'] = erg['erw'] = None
    if erg['familie'] is not None and erg['familie'] > 80:
        erg['familie'] = None
    kurz = ' '.join(t.split())
    if re.search(r'€|euro|eintritt|preis|frei|kostenlos|kostenfrei|spende|gebühr|tarif|ticket', kurz.lower()):
        erg['text'] = kurz[:160] + ('…' if len(kurz) > 160 else '')
    else:
        erg['text'] = None
    erg['url'] = url
    return erg


_TAG = {'Monday': 'Mo', 'Tuesday': 'Tu', 'Wednesday': 'We', 'Thursday': 'Th',
        'Friday': 'Fr', 'Saturday': 'Sa', 'Sunday': 'Su'}
_REIHE = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
_MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _tage_osm(tage):
    idx = sorted(_REIHE.index(_TAG[t]) for t in tage if t in _TAG)
    if not idx:
        return None
    teile, i = [], 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        teile.append(_REIHE[idx[i]] if i == j else
                     (f'{_REIHE[idx[i]]},{_REIHE[idx[j]]}' if j == i + 1 else f'{_REIHE[idx[i]]}-{_REIHE[idx[j]]}'))
        i = j + 1
    return ','.join(teile)


def _zeitraum(von, bis):
    """Saison als OSM-Monatsbereich oder None (= ganzjährig)."""
    if bis is None or (bis - von).days >= 360:
        return None
    return f'{_MON[von.month - 1]} {von.day:02d}-{_MON[bis.month - 1]} {bis.day:02d}'


def zeiten_osm(item, heute):
    """Wöchentliche Öffnungszeiten → OSM-Text; None, wenn unklar."""
    gruppen = {}
    for t in item.get('timeIntervals') or []:
        if t.get('freq') != 'Weekly' or not t.get('weekdays'):
            continue
        try:
            von = dt.datetime.fromisoformat(t['start'])
            bis = dt.datetime.fromisoformat(t['end'])
        except (KeyError, ValueError):
            continue
        ende = None
        if t.get('repeatUntil'):
            try:
                ende = dt.datetime.fromisoformat(t['repeatUntil']).date()
            except ValueError:
                return None
            if ende < heute:
                continue  # abgelaufene Regel
        if (von.hour, von.minute) == (0, 0) and (bis.hour, bis.minute) in ((0, 0), (23, 59)):
            return None  # „ganztägig“ ohne echte Zeiten → nicht raten
        if bis <= von and bis.date() == von.date():
            return None
        b = '24:00' if (bis.hour, bis.minute) == (0, 0) else f'{bis.hour:02d}:{bis.minute:02d}'
        if (bis.hour, bis.minute) == (23, 59):
            b = '24:00'
        if not _tage_osm(t['weekdays']):
            continue
        saison = None
        if ende is not None and (ende - von.date()).days < 360:
            if von.date() > heute + dt.timedelta(days=366):
                continue
            saison = _zeitraum(von.date(), ende)
        spanne = f'{von.hour:02d}:{von.minute:02d}-{b}'
        g2 = gruppen.setdefault(saison, {})
        g2.setdefault(spanne, set()).update(x for x in t['weekdays'] if x in _TAG)
    if not gruppen:
        return None
    teile = []
    for saison in sorted(gruppen, key=lambda s: (s is not None, s or '')):
        # gleiche Uhrzeit → Tage zusammenfassen („Mo-Su 11:00-17:00“)
        regel = ', '.join(f'{_tage_osm(tage)} {spanne}' for spanne, tage in
                          sorted(gruppen[saison].items(), key=lambda x: min(_REIHE.index(_TAG[d]) for d in x[1])))
        teile.append(f'{saison}: {regel}' if saison else regel)
    return '; '.join(teile)


def main():
    heute = g.heute()
    cache = os.environ.get('ET4_POI_JSON')  # nur zum Testen: lokal gespeicherter Abruf
    items = json.load(open(cache)) if cache else g.et4_alle('POI')[0]
    orte, zaehler = [], {'gesamt': len(items), 'lizenz_nicht_offen': 0, 'unwichtig': 0,
                         'ohne_daten': 0, 'mit_preis_zahl': 0, 'frei': 0, 'mit_zeiten': 0}
    for it in items:
        if g.et4_lizenz(it) not in g.OFFENE_LIZENZEN:
            zaehler['lizenz_nicht_offen'] += 1
            continue
        kats = [k for k in it.get('categories') or [] if k]
        if kats and all(k in UNWICHTIG for k in kats):
            zaehler['unwichtig'] += 1
            continue
        lat, lon = g.et4_koordinaten(it)
        name = (it.get('title') or '').strip()
        if lat is None or not name:
            zaehler['ohne_daten'] += 1
            continue
        preis = preis_aus_text(g.et4_text(it, 'PRICE_INFO'), name)
        zeiten = zeiten_osm(it, heute)
        if preis and not any(preis.get(k) not in (None, False) for k in ('erw', 'kind', 'familie', 'frei', 'text', 'url')):
            preis = None
        if not preis and not zeiten:
            zaehler['ohne_daten'] += 1
            continue
        if preis and any(preis[k] is not None for k in ('erw', 'kind', 'familie')):
            zaehler['mit_preis_zahl'] += 1
        if preis and preis['frei']:
            zaehler['frei'] += 1
        if zeiten:
            zaehler['mit_zeiten'] += 1
        eintrag = {'id': f'nrw:{it.get("id")}', 'quelle': 'tnrw', 'name': name, 'lat': lat, 'lon': lon,
                   'ort': it.get('city') or '', 'kategorien': kats[:3],
                   'web': it.get('web') if str(it.get('web', '')).startswith('http') else '',
                   'lizenz': g.et4_lizenz(it), 'geaendert': (it.get('changed') or '')[:10]}
        if preis:
            p = {k: v for k, v in preis.items() if v is not None and v is not False and v != ''}
            if p:
                eintrag['preis'] = p
        if zeiten:
            eintrag['zeiten'] = zeiten
        orte.append(eintrag)
    # Von Betreiber-Websites gelesene Werte (pipeline/websites.py) anhängen –
    # die App nimmt bei mehreren Treffern für denselben Ort den ersten (Tourismus NRW).
    web = os.path.join(g.AUSGABE, 'websites.json')
    if os.path.exists(web):
        w = json.load(open(web, encoding='utf-8')).get('orte', [])
        orte.extend(w)
        zaehler['websites'] = len(w)
    if len(orte) < 500:
        print('Zu wenige Orte – docs/orte.json bleibt unverändert.', zaehler)
        sys.exit(1)
    daten = {
        'version': 1,
        'stand': g.jetzt_iso(),
        'quellen': {'tnrw': {'name': 'Tourismus NRW e.V. – Open Data Hub (destination.one)',
                             'lizenz': 'je Eintrag (hier nur gemeinfrei/CC)',
                             'url': 'https://tourismusverband.nrw/open-data-finder'},
                    'web': {'name': 'Website des Betreibers (automatisch gelesen, bitte prüfen)'}},
        'bericht': zaehler,
        'orte': orte,
    }
    pfad = g.schreibe('orte.json', daten)
    print(f'{len(orte)} Orte → {pfad}')
    print(json.dumps(zaehler, ensure_ascii=False))


if __name__ == '__main__':
    main()
