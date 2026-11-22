#!/usr/bin/env python3
"""Erlebsy: Eintritt und Öffnungszeiten von den Websites der Betreiber lesen.

Eingabe:  pipeline/websites_liste.json – Ausflugsziele mit Website (aus
          OpenStreetMap, © OpenStreetMap-Mitwirkende, ODbL).
Ausgabe:  docs/websites.json – nur Fakten: Preise (Erwachsene/Kind/Familie bzw.
          „frei“), Öffnungszeiten (nur aus strukturierten schema.org-Daten),
          Quelle (URL der gelesenen Seite) und Datum.

Regeln: robots.txt wird beachtet, höchstens 3 Seiten je Website, 1 Abruf pro
Sekunde, keine Texte oder Bilder werden übernommen. Was nicht eindeutig ist,
bleibt leer (die App zeigt dann „?“). Werte von Websites gelten als
„automatisch gelesen – bitte prüfen“.

Wiederaufnehmbar: pipeline/websites_stand.json merkt sich, welche Website wann
gelesen wurde; je Lauf werden höchstens --max Websites (älteste zuerst) gelesen.

Gebrauch: python3 pipeline/websites.py [--max 400]
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemeinsam as g  # noqa: E402

LISTE = os.path.join(g.HIER, 'websites_liste.json')
STAND = os.path.join(g.HIER, 'websites_stand.json')
NEU_LESEN_NACH_TAGEN = 30

PREIS_LINK = re.compile(r'eintritt|preis|ticket|tarif|besuch|öffnungszeit|oeffnungszeit|'
                        r'info|planen|anreise|admission|prices', re.I)
_letzter_abruf = {}


def _hole_html(url):
    host = urllib.parse.urlparse(url).netloc
    warte = 1.0 - (time.time() - _letzter_abruf.get(host, 0))
    if warte > 0:
        time.sleep(warte)
    _letzter_abruf[host] = time.time()
    roh = g.hole(url, versuche=1, timeout=15)
    if len(roh) > 3_000_000:
        return ''
    for kodierung in ('utf-8', 'latin-1'):
        try:
            return roh.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return ''


def text_aus_html(seite):
    s = re.sub(r'(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>', ' ', seite)
    s = re.sub(r'(?i)<br\s*/?>|</(p|div|li|tr|h\d|td|th|dd|dt)>', '\n', s)
    s = re.sub(r'(?s)<[^>]+>', ' ', s)
    s = html.unescape(s)
    zeilen = [' '.join(z.split()) for z in s.split('\n')]
    return [z for z in zeilen if z]


_BETRAG = re.compile(r'(?:€\s*(\d{1,3}(?:[.,]\d{1,2})?)|(\d{1,3}(?:[.,]\s?\d{1,2})?)\s*(?:€|euro\b|eur\b))', re.I)
_NICHT = re.compile(r'ermäßigt|ermässigt|erm\.|reduziert|gruppe|schul|klasse|student|senior|rentner|gdb|'
                    r'schwerbehindert|behindert|begleit|jahres|saison|dauer|abo|zehner|10er|abend|'
                    r'führung|fuehrung|workshop|kurs|yoga|seminar|anmeld|kosten:|geburtstag|miete|'
                    r'park|gutschein|mitglied|sonder|kombi|audioguide|katalog|shop|versand|spende|'
                    r'rabatt|happy|online-?vorteil|stunde|minute', re.I)


def _betrag(z):
    m = _BETRAG.search(z)
    if not m:
        return None
    w = float((m.group(1) or m.group(2)).replace(' ', '').replace(',', '.'))
    return w if 0 < w <= 150 else None


def preis_aus_web(zeilen):
    """Nur eindeutig beschriftete Preise: „Erwachsene/Regulär …“, „Kinder …“,
    „Familie …“; Kinder/unter-18 „frei“ → 0. Alles andere bleibt leer."""
    erg = {'erw': None, 'kind': None, 'familie': None}
    for z in zeilen:
        zl = z.lower()
        if len(zl) > 140 or _NICHT.search(zl):
            continue
        b = _betrag(zl)
        # Kleinkinder („bis 3/6 Jahre frei“) sind nicht der Kinderpreis.
        if re.search(r'(bis|unter|bis zu)\s*[1-6]\s*(j\b|jahr)|kleinkind|baby', zl):
            continue
        kind_frei = re.search(r'(kinder|jugendliche|unter 1[0-9]|bis 1[0-9] jahre?).{0,40}'
                              r'(frei\b|kostenlos|kostenfrei|0,00|0 €)', zl)
        if kind_frei and erg['kind'] is None:
            erg['kind'] = 0.0
            continue
        if b is None:
            continue
        if re.search(r'famili', zl) and erg['familie'] is None:
            erg['familie'] = b
        elif re.search(r'\bkind|kinder|jugendliche|unter 1[0-9]|bis 1[0-9] jahre', zl):
            if erg['kind'] is None:
                erg['kind'] = b
        elif re.search(r'erwachsen|regulär|regulaer|normalpreis|vollzahler|vollpreis|\berw\.?\b|'
                       r'^eintritt:?\s*(€\s*)?\d', zl) and erg['erw'] is None:
            erg['erw'] = b
    if erg['erw'] is None and erg['familie'] is None:
        return None  # ohne Erwachsenen-/Familienpreis zu unsicher
    if erg['kind'] is not None and erg['erw'] is not None and erg['kind'] > erg['erw']:
        return None
    return erg


def preis_block(zeilen):
    """Zeilen rund um „Eintritt/Preise“ mit Euro-Beträgen (max. 25 Zeilen)."""
    treffer = []
    for i, z in enumerate(zeilen):
        if re.search(r'eintritt|preise|tickets?\b|tarife', z, re.I):
            block = zeilen[i:i + 25]
            if sum(1 for b in block if re.search(r'\d\s*(€|euro|eur\b)|€\s*\d', b, re.I)) >= 1:
                treffer.extend(block)
                if len(treffer) > 60:
                    break
    return treffer


_TAGE = {'monday': 'Mo', 'tuesday': 'Tu', 'wednesday': 'We', 'thursday': 'Th',
         'friday': 'Fr', 'saturday': 'Sa', 'sunday': 'Su'}


def _jsonld_objekte(seite):
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', seite):
        try:
            stapel = [json.loads(m.group(1).strip())]
        except ValueError:
            continue
        while stapel:
            x = stapel.pop()
            if isinstance(x, list):
                stapel.extend(x)
            elif isinstance(x, dict):
                yield x
                for k in ('@graph', 'location', 'containsPlace'):
                    if isinstance(x.get(k), (list, dict)):
                        stapel.append(x[k])


_ORTSTYPEN = {'Museum', 'TouristAttraction', 'Zoo', 'AmusementPark', 'Aquarium', 'LocalBusiness',
              'EntertainmentBusiness', 'SportsActivityLocation', 'PublicSwimmingPool', 'Park',
              'Place', 'LandmarksOrHistoricalBuildings', 'CivicStructure', 'ArtGallery',
              'ChildCare', 'Playground', 'StadiumOrArena', 'ExerciseGym', 'SkiResort'}


def _woerter(s):
    s = s.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    return {w for w in re.split(r'[^a-z0-9]+', s) if len(w) >= 4} - {
        'museum', 'park', 'haus', 'stadt', 'kirche', 'schloss', 'burg', 'zoo', 'tierpark', 'bad'}


def _name_passt(a, b):
    na, nb = re.sub(r'[^a-z0-9]', '', a.lower()), re.sub(r'[^a-z0-9]', '', b.lower())
    return bool(na and nb and (na in nb or nb in na or _woerter(a) & _woerter(b)))


def zeiten_aus_jsonld(seite, name=''):
    """schema.org openingHoursSpecification/openingHours → OSM-Text oder None."""
    for o in _jsonld_objekte(seite):
        typ = o.get('@type')
        typen = typ if isinstance(typ, list) else [typ]
        if not any(isinstance(t, str) and t in _ORTSTYPEN for t in typen):
            continue
        if name and not _name_passt(name, str(o.get('name', ''))):
            continue
        spec = o.get('openingHoursSpecification')
        if isinstance(spec, dict):
            spec = [spec]
        if isinstance(spec, list) and spec:
            regeln = {}
            for s in spec:
                if not isinstance(s, dict) or s.get('validFrom') or s.get('validThrough'):
                    return None  # Saison-/Sonderregeln: lieber nicht raten
                tage = s.get('dayOfWeek')
                tage = tage if isinstance(tage, list) else [tage]
                von, bis = str(s.get('opens', ''))[:5], str(s.get('closes', ''))[:5]
                if not re.match(r'\d\d:\d\d$', von) or not re.match(r'\d\d:\d\d$', bis):
                    return None
                for t in tage:
                    k = _TAGE.get(str(t).rsplit('/', 1)[-1].lower())
                    if k:
                        regeln.setdefault(f'{von}-{bis}', []).append(k)
            if regeln:
                reihe = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
                teile = [f'{",".join(sorted(set(t), key=reihe.index))} {sp}' for sp, t in regeln.items()]
                return ', '.join(teile)
        oh = o.get('openingHours')
        if isinstance(oh, str):
            oh = [oh]
        if isinstance(oh, list) and oh and all(isinstance(x, str) for x in oh):
            text = '; '.join(x.strip() for x in oh)
            if re.match(r'^((Mo|Tu|We|Th|Fr|Sa|Su)[-,A-Za-z]*\s+\d\d:\d\d-\d\d:\d\d[;, ]*)+$', text):
                return text
    return None


def lies_website(url, name=''):
    """→ dict(preis, zeiten, quelle_url) oder None."""
    if not url.startswith('http'):
        return None
    seite = _hole_html(url)
    if not seite:
        return None
    basis = urllib.parse.urlparse(url)
    zeiten = zeiten_aus_jsonld(seite, name)
    seiten = [(url, seite)]
    # Links zu Preis-/Besuchsseiten auf derselben Domain
    kandidaten = []
    for m in re.finditer(r'(?is)<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', seite):
        href, text = m.group(1), re.sub(r'<[^>]+>', ' ', m.group(2))
        ziel = urllib.parse.urljoin(url, html.unescape(href))
        p = urllib.parse.urlparse(ziel)
        if p.netloc != basis.netloc or p.scheme not in ('http', 'https'):
            continue
        if re.search(r'\.(pdf|jpg|png|zip)$', p.path, re.I):
            continue
        rang = 2 if re.search(r'eintritt|preis|ticket|tarif|admission|prices', f'{text} {href}', re.I) else \
            (1 if PREIS_LINK.search(f'{text} {href}') else 0)
        if rang and ziel not in [k[1] for k in kandidaten] and ziel.rstrip('/') != url.rstrip('/'):
            kandidaten.append((rang, ziel))
    kandidaten.sort(key=lambda k: -k[0])
    for _, ziel in kandidaten[:2]:
        try:
            if g.darf(ziel):
                seiten.append((ziel, _hole_html(ziel)))
        except Exception:  # noqa: BLE001
            continue
    bester = None
    for quelle, s in seiten:
        if not s:
            continue
        zeiten = zeiten or zeiten_aus_jsonld(s, name)
        # Unterseiten nur, wenn sie den Ort nennen (sonst z. B. Stadtportal-Seite
        # über etwas anderes).
        if quelle != url and name and not _name_passt(name, ' '.join(text_aus_html(s)[:400])):
            continue
        block = preis_block(text_aus_html(s))
        if not block:
            continue
        p = preis_aus_web(block)
        if not p:
            continue
        zahlen = sum(1 for k in ('erw', 'kind', 'familie') if p.get(k) is not None)
        if zahlen and (bester is None or zahlen > bester[0]):
            bester = (zahlen, quelle, p)
    if bester is None and not zeiten:
        return None
    erg = {}
    if bester:
        _, quelle, p = bester
        erg['preis'] = {k: v for k, v in p.items() if k in ('erw', 'kind', 'familie') and v is not None}
        erg['preis']['url'] = quelle
        erg['quelle_url'] = quelle
    if zeiten:
        erg['zeiten'] = zeiten
        erg.setdefault('quelle_url', url)
    return erg


def main():
    max_n = 400
    if '--max' in sys.argv:
        max_n = int(sys.argv[sys.argv.index('--max') + 1])
    liste = json.load(open(LISTE, encoding='utf-8'))['orte']
    stand = json.load(open(STAND, encoding='utf-8')) if os.path.exists(STAND) else {}
    heute = g.heute()
    alt = {}
    ziel = os.path.join(g.AUSGABE, 'websites.json')
    if os.path.exists(ziel):
        alt = {o['id']: o for o in json.load(open(ziel, encoding='utf-8')).get('orte', [])}

    def faellig(o):
        s = stand.get(o['id'])
        return s is None or (heute - dt.date.fromisoformat(s['datum'])).days >= NEU_LESEN_NACH_TAGEN

    # Priorität: Liste ist nach Wichtigkeit sortiert (Lesezeichen, Köln/Bonn, NRW).
    offen = [o for o in liste if faellig(o)][:max_n]
    start = time.time()
    for i, o in enumerate(offen):
        try:
            erg = lies_website(o['website'], o['name'])
            status = 'ok' if erg else 'nichts'
        except PermissionError:
            erg, status = None, 'robots'
        except Exception as e:  # noqa: BLE001
            erg, status = None, f'fehler: {type(e).__name__}'
        stand[o['id']] = {'datum': heute.isoformat(), 'status': status}
        if erg:
            alt[o['id']] = {'id': o['id'], 'name': o['name'], 'lat': o['lat'], 'lon': o['lon'],
                            'quelle': 'web', 'geaendert': heute.isoformat(), **erg}
        elif status in ('nichts', 'robots'):
            alt.pop(o['id'], None)
        if (i + 1) % 25 == 0:
            print(f'{i + 1}/{len(offen)} ({int(time.time() - start)} s), Treffer gesamt {len(alt)}')
        if time.time() - start > 5 * 3600:
            break
    with open(STAND, 'w', encoding='utf-8') as f:
        json.dump(stand, f, ensure_ascii=False, indent=0, sort_keys=True)
    orte = sorted(alt.values(), key=lambda o: o['id'])
    g.schreibe('websites.json', {
        'version': 1, 'stand': g.jetzt_iso(),
        'quelle': {'name': 'Websites der Betreiber (automatisch gelesen, bitte prüfen)',
                   'liste': 'OpenStreetMap-Mitwirkende (ODbL)'},
        'bericht': {'gelesen': len(offen), 'treffer': len(orte),
                    'mit_preis': sum(1 for o in orte if o.get('preis')),
                    'mit_zeiten': sum(1 for o in orte if o.get('zeiten'))},
        'orte': orte})
    print(f'{len(orte)} Orte mit Website-Daten')


if __name__ == '__main__':
    main()
