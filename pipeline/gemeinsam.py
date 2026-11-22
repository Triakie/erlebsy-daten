"""Gemeinsame Helfer für die Erlebsy-Daten-Pipeline (nur Standardbibliothek)."""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.robotparser

UA = 'ErlebsyDaten/1.0 (+https://github.com/Triakie/erlebsy-daten; liest nur offene Daten)'
HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
AUSGABE = os.path.join(WURZEL, 'docs')

_robots = {}


def darf(url):
    """robots.txt beachten (fehlt sie oder ist sie kein Text: erlaubt)."""
    p = urllib.parse.urlparse(url)
    basis = f'{p.scheme}://{p.netloc}'
    if basis not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                basis + '/robots.txt', headers={'User-Agent': UA}), timeout=20)
            text = r.read().decode('utf-8', 'ignore')
            rp.parse(text.splitlines() if 'user-agent' in text.lower() else [])
        except Exception:  # noqa: BLE001 – keine robots.txt = erlaubt
            rp.parse([])
        _robots[basis] = rp
    return _robots[basis].can_fetch(UA, url)


def hole(url, versuche=3, pause=2.0):
    if not darf(url):
        raise PermissionError('robots.txt verbietet ' + url)
    fehler = None
    for i in range(versuche):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={'User-Agent': UA, 'Accept': 'application/json'}), timeout=60)
            return r.read()
        except Exception as e:  # noqa: BLE001
            fehler = e
            time.sleep(pause * (i + 1))
    raise fehler


def hole_json(url, **kw):
    return json.loads(hole(url, **kw).decode('utf-8'))


def heute():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=1))).date()


def jetzt_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def schreibe(name, daten):
    os.makedirs(AUSGABE, exist_ok=True)
    pfad = os.path.join(AUSGABE, name)
    with open(pfad + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(daten, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(pfad + '.tmp', pfad)
    return pfad


def et4_alle(typ, pause=1.0, seite=500, max_seiten=80):
    """Alle Einträge eines Typs aus dem Open Data Hub von Tourismus NRW (eT4)."""
    basis = ('https://meta.et4.de/rest.ashx/search/?experience=open-data-nrw-tourismus'
             f'&type={typ}&template=ET2014A.json&q=&limit={seite}')
    alle, offset, gesamt = [], 0, None
    for _ in range(max_seiten):
        d = hole_json(f'{basis}&offset={offset}')
        if d.get('status') != 'OK':
            raise RuntimeError(f'eT4 {typ}: Status {d.get("status")}')
        gesamt = d.get('overallcount', 0)
        items = d.get('items') or []
        alle.extend(items)
        offset += seite
        if not items or offset >= gesamt:
            break
        time.sleep(pause)
    return alle, gesamt


OFFENE_LIZENZEN = {'PD', 'CC0', 'CC-BY', 'CC-BY-SA', 'CC BY', 'CC BY-SA', 'CC-BY 4.0', 'CC-BY-SA 4.0'}


def et4_lizenz(item):
    """Lizenz des Eintrags (Attribut "license"); None = unbekannt → nicht nutzen."""
    for a in item.get('attributes') or []:
        if a.get('key') == 'license':
            return (a.get('value') or '').strip() or None
    return None


def et4_text(item, rel):
    for t in item.get('texts') or []:
        if t.get('rel') == rel and t.get('type', 'text/plain') == 'text/plain' and t.get('value'):
            return t['value'].strip()
    return ''


def et4_koordinaten(item):
    g = ((item.get('geo') or {}).get('main') or {})
    lat, lon = g.get('latitude'), g.get('longitude')
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and lat and lon:
        return round(lat, 6), round(lon, 6)
    return None, None
