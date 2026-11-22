#!/usr/bin/env python3
"""Erlebsy: kommende Familien-/Freizeit-Events aus offenen Quellen → docs/events.json.

Quellen (nur offene Daten mit klarer Lizenz, keine Portale, keine sozialen Netzwerke):
  - Stadt Köln, Veranstaltungskalender (Open Data, dl-de/zero-2.0, nächste 7 Tage)
  - Tourismus NRW e.V., Open Data Hub (eT4/destination.one, Lizenz je Eintrag;
    übernommen werden nur offene Lizenzen: PD, CC0, CC BY, CC BY-SA)
  - pipeline/manuell.json: recherchierte Termine (Quelle + Stand je Eintrag)

Übernommen werden nur Fakten (Titel, Datum, Uhrzeit, Ort, Koordinaten, Link,
kurzer Preis-Hinweis) – keine Beschreibungstexte, keine Bilder.
Die App lädt die Datei beim Start, ordnet sie Orten zu (Name + Nähe) und löscht
Vergangenes selbst.

Gebrauch: python3 pipeline/events.py  (schreibt docs/events.json)
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemeinsam as g  # noqa: E402

HORIZONT_TAGE = 120
MAX_TERMINE_PRO_EVENT = 6

# Familien-Bezug: Treffer im Titel/Kategorie/Stichworten.
FAMILIE = re.compile(
    r'kinder|kind\b|kids|famili|eltern|jugend|baby|kita|schüler|ferien|märchen|puppen|'
    r'zirkus|zauber|basteln|bastel|spielen|spielefest|spieletag|zoo|tierpark|wildpark|'
    r'bauernhof|ponyreit|streichelzoo|nikolaus|weihnachtsmarkt|adventsmarkt|christkind|'
    r'laternen|martinszug|sankt martin|st\. martin|ostereier|osterfeuer|halloween|kürbis|'
    r'kirmes|jahrmarkt|volksfest|stadtfest|dorffest|lichterfest|eislauf|eisbahn|schlittschuh|'
    r'rodel|mitmach|entdecker|forscher|experiment|planetarium|theater für|figurentheater|'
    r'kasper|vorlese|bilderbuch|rallye|schnitzeljagd|abenteuer|ritter|piraten|dino',
    re.I)

# Klar nicht für Familien (wird auch bei Familien-Kategorie aussortiert).
AUSSCHLUSS = re.compile(
    r'\bü ?\d\d\b|ue\d\d-|party|disco|clubnacht|after ?work|tasting|weinprobe|whisk|bier ?probe|'
    r'single|erotik|stammtisch|selbsthilfe|sprechstunde|blutspende|beratung|sitzung|'
    r'gottesdienst|messe für|andacht|gebet|trauer|seniorentreff|demenz|bewerbung|'
    r'krimidinner|comedy|kabarett|stand-?up|poetry|lesung für erwachsene|schnitzeltag|'
    r'exklusiv für|brauhaus|kneipe|absinth|grünen fee|cocktail|änderung|aufhebung|'
    r'bebauungsplan|bauleitplan|planfeststellung|offenlage|bürgerbeteiligung|'
    r'nur für gäste|wochenmarkt|bauernmarkt|flohmarkt für erwachsene|'
    r'brunch|frühstück|dinner|menü|buffet|yoga|pilates|qigong|meditation|vortrag|seminar|'
    r'kurs:|workshop für erwachsene|vernissage|finissage|ratssitzung|bürgersprechstunde',
    re.I)

# Kategorien, die auch ohne Familien-Stichwort passen (Ausflug für alle).
KATEGORIEN_FREIZEIT = {
    'Kinderprogramm', 'Kinder- und Jugendtheater', 'Weihnachtsmarkt', 'Markt',
    'Fest/Ball', 'Brauchtum/Kultur', 'Ausflug/Exkursion', 'Führung/Besichtigung',
    'Ausstellung', 'Sport', 'Volksfest', 'Kirmes', 'Natur', 'Natur/Umwelt',
    'Stadtfest', 'Festival', 'Freizeit', 'Familie', 'Familienprogramm',
    'Mittelaltermarkt', 'Freilichtmuseum',
}


def _datum(s):
    try:
        return dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _uhr(von, bis, ganztags):
    if ganztags or von is None:
        return ''
    if von.hour == 0 and von.minute == 0:
        return ''
    a = f'{von.hour}:{von.minute:02d}'.replace(':00', '')
    if bis is not None and bis.date() == von.date() and (bis.hour, bis.minute) not in ((0, 0), (23, 59)) and bis > von:
        b = f'{bis.hour}:{bis.minute:02d}'.replace(':00', '')
        return f'{a}–{b} Uhr'
    return f'ab {a} Uhr'


def _wochentage(tage):
    """[Monday, Tuesday, Wednesday, Friday] → „Mo–Mi, Fr“."""
    k = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    kurz = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    idx = [i for i, t in enumerate(k) if t in (tage or [])]
    teile, i = [], 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        if j - i >= 2:
            teile.append(f'{kurz[idx[i]]}–{kurz[idx[j]]}')
        else:
            teile.extend(kurz[idx[x]] for x in range(i, j + 1))
        i = j + 1
    return ', '.join(teile)


def termine_et4(item, heute, horizont):
    """Kommende Termine eines eT4-Events: [(von, bis, uhrzeit)] (Datum als date)."""
    out = []
    abgesagt = set()
    for o in item.get('occurrences') or []:
        for a in o.get('attributes') or []:
            if a.get('key') == 'EventStatus' and a.get('value') == 'cancelled':
                d = _datum(o.get('start'))
                if d:
                    abgesagt.add(d.date())
    for t in item.get('timeIntervals') or []:
        von, bis = _datum(t.get('start')), _datum(t.get('end'))
        if von is None:
            continue
        uhr = _uhr(von, bis, t.get('hideEnd') and von.hour == 0)
        freq = t.get('freq')
        if freq:
            ende = _datum(t.get('repeatUntil'))
            ende_d = ende.date() if ende else horizont
            start_d = max(von.date(), heute)
            if ende_d < heute or start_d > horizont:
                continue
            tage = _wochentage(t.get('weekdays'))
            if freq == 'Weekly' and tage and tage != 'Mo–So':
                uhr = (tage + (' ' + uhr if uhr else '')).strip()
            out.append((start_d, min(ende_d, horizont + dt.timedelta(days=365)), uhr))
        else:
            vd = von.date()
            bd = bis.date() if bis and bis.date() >= vd else vd
            if bd < heute or vd > horizont or vd in abgesagt:
                continue
            out.append((vd, bd, uhr))
    out.sort()
    # Gleicher Zeitraum mit mehreren Wochentags-Regeln (z. B. „So–Mi 11–21,
    # Do, Fr 11–22“) → ein Termin mit allen Zeiten.
    eindeutig, nach_tagen = [], {}
    for von, bis, uhr in out:
        # Zeiträume (Märkte, Ausstellungen) nach Ende zusammenfassen – die
        # Wochentags-Regeln beginnen oft an verschiedenen Tagen.
        k = ('bis', bis) if (bis - von).days >= 6 else (von, bis)
        if k in nach_tagen:
            alt = eindeutig[nach_tagen[k]]
            uhr_neu = alt[2]
            if uhr and uhr not in alt[2]:
                uhr_neu = f'{alt[2]}; {uhr}' if alt[2] else uhr
            eindeutig[nach_tagen[k]] = (min(von, alt[0]), bis, uhr_neu)
            continue
        nach_tagen[k] = len(eindeutig)
        eindeutig.append((von, bis, uhr))
    return eindeutig[:MAX_TERMINE_PRO_EVENT]


def _link(item):
    for m in item.get('media_objects') or []:
        if m.get('rel') in ('booking', 'ticket', 'eventwebsite') and str(m.get('url', '')).startswith('http'):
            return m['url']
    w = item.get('web') or ''
    return w if w.startswith('http') else ''


def _kuerze(t, n=70):
    t = ' '.join((t or '').split())
    return t if len(t) <= n else t[:n - 1].rstrip(' ;,') + '…'


def _kurzpreis(text):
    if not text:
        return ''
    t = ' '.join(text.split())
    if re.search(r'kostenlos|kostenfrei|eintritt frei|freier eintritt|frei\b', t, re.I) and not re.search(r'\d+[,.]?\d* ?€', t):
        return 'Eintritt frei'
    t = re.sub(r'^Preise\s*', '', t)
    return t[:90] + ('…' if len(t) > 90 else '')


KATEGORIEN_AUS = {'Gesundheit/Wellness', 'Kurs/Seminar/Hobby', 'Vortrag/Lesung',
                  'Party/Nightlife', 'Genuss/Gourmet', 'Comedy', 'Kabarett', 'Tagung/Kongress'}


def bewerte(titel, kategorien, stichworte=''):
    """(aufnehmen, familie)."""
    text = f'{titel} {" ".join(kategorien)} {stichworte}'
    if AUSSCHLUSS.search(titel):
        return False, False
    if any(k in KATEGORIEN_AUS for k in kategorien) and not FAMILIE.search(titel):
        return False, False
    fam = bool(FAMILIE.search(text))
    if fam:
        return True, True
    if any(k in KATEGORIEN_FREIZEIT for k in kategorien):
        return True, False
    return False, False


def aus_et4(items, heute, horizont):
    out, gezaehlt = [], {'gesamt': len(items), 'lizenz_nicht_offen': 0, 'ohne_termin': 0,
                         'nicht_passend': 0, 'ohne_ort': 0}
    for it in items:
        liz = g.et4_lizenz(it)
        if liz not in g.OFFENE_LIZENZEN:
            gezaehlt['lizenz_nicht_offen'] += 1
            continue
        titel = (it.get('title') or '').strip()
        kats = [k for k in it.get('categories') or [] if k]
        stich = ' '.join(k for k in it.get('keywords') or [] if not k.startswith('import_'))
        ok, fam = bewerte(titel, kats, stich)
        if not ok or not titel:
            gezaehlt['nicht_passend'] += 1
            continue
        lat, lon = g.et4_koordinaten(it)
        if lat is None:
            gezaehlt['ohne_ort'] += 1
            continue
        termine = termine_et4(it, heute, horizont)
        if not termine:
            gezaehlt['ohne_termin'] += 1
            continue
        ort_name, veranstalter = '', ''
        for a in it.get('addresses') or []:
            if a.get('rel') in ('venue', 'location') and a.get('name') and not ort_name:
                ort_name = a['name']
            if a.get('rel') == 'organizer' and a.get('name') and not veranstalter:
                veranstalter = a['name']
        for von, bis, uhr in termine:
            out.append({
                'id': f'nrw:{it.get("id")}:{von.isoformat()}',
                'titel': titel,
                'von': von.isoformat(),
                'bis': bis.isoformat() if bis != von else None,
                'uhrzeit': uhr,
                'ort': it.get('city') or '',
                'ort_name': ort_name,
                'veranstalter': veranstalter,
                'strasse': it.get('street') or '',
                'lat': lat, 'lon': lon,
                'kategorie': kats[0] if kats else '',
                'familie': fam,
                'preis': _kurzpreis(g.et4_text(it, 'PRICE_INFO')),
                'link': _link(it),
                'quelle': 'nrw',
                'lizenz': liz,
            })
    return out, gezaehlt


def aus_koeln(heute):
    d = g.hole_json('https://www.stadt-koeln.de/externe-dienste/open-data/events-od.php')
    out = []
    for it in d.get('items') or []:
        titel = (it.get('title') or '').strip()
        ok, fam = bewerte(titel, [], it.get('description') or '')
        # Städtischer Kalender: Bibliotheken, Museen, Feste – nur Ausschluss anwenden.
        if not titel or (not ok and AUSSCHLUSS.search(titel)):
            continue
        try:
            von = dt.date.fromisoformat(it['beginndatum'])
            bis = dt.date.fromisoformat(it.get('endedatum') or it['beginndatum'])
        except (KeyError, ValueError):
            continue
        if bis < heute or re.match(r'abgesagt', titel, re.I) or 'abgesagt' in (it.get('uhrzeit') or '').lower():
            continue
        try:
            lat, lon = float(it['latitude']), float(it['longitude'])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        link = (it.get('link') or '').replace('http://', 'https://')
        preis = _kurzpreis(it.get('preis') or '')
        out.append({
            'id': f'koeln:{re.sub(r"[^0-9]", "", link)[-8:] or titel}:{von.isoformat()}',
            'titel': titel,
            'von': von.isoformat(),
            'bis': bis.isoformat() if bis != von else None,
            'uhrzeit': _kuerze(re.sub(r'\s*<br\s*/?>\s*', '; ', it.get('uhrzeit') or '')),
            'ort': it.get('ort') or 'Köln',
            'ort_name': it.get('veranstaltungsort') or '',
            'strasse': ' '.join(x for x in [it.get('strasse'), it.get('hausnummer')] if x),
            'lat': lat, 'lon': lon,
            'kategorie': '',
            'familie': fam,
            'preis': preis,
            'link': link,
            'quelle': 'koeln',
            'lizenz': 'dl-de/zero-2.0',
        })
    return out


def aus_manuell(heute):
    pfad = os.path.join(g.HIER, 'manuell.json')
    if not os.path.exists(pfad):
        return []
    d = json.load(open(pfad, encoding='utf-8'))
    out = []
    for e in d.get('events') or []:
        bis = e.get('bis') or e.get('von')
        if not e.get('von') or dt.date.fromisoformat(bis) < heute:
            continue
        out.append({**e, 'id': f'manuell:{e["titel"]}:{e["von"]}', 'quelle': 'manuell',
                    'familie': e.get('familie', True)})
    return out


def _schluessel(e):
    """Gleicher Titel, gleiches Ende, gleicher Ort (Stadt) = dasselbe Event."""
    t = re.sub(r'[^a-z0-9äöüß]', '', e['titel'].lower())
    ort = re.sub(r'[^a-z0-9äöüß]', '', (e.get('ort') or '').lower().split(',')[0])
    return f'{t}|{e.get("bis") or e["von"]}|{ort}'


def main():
    heute = g.heute()
    horizont = heute + dt.timedelta(days=HORIZONT_TAGE)
    berichte, alle = {}, []
    manuell = aus_manuell(heute)
    alle += manuell
    berichte['manuell'] = len(manuell)
    try:
        k = aus_koeln(heute)
        alle += k
        berichte['koeln'] = len(k)
    except Exception as e:  # noqa: BLE001 – eine Quelle darf ausfallen
        berichte['koeln'] = f'Fehler: {e}'
    try:
        cache = os.environ.get('ET4_EVENTS_JSON')  # nur zum Testen: lokal gespeicherter Abruf
        items = json.load(open(cache)) if cache else g.et4_alle('Event')[0]
        n, z = aus_et4(items, heute, horizont)
        alle += n
        berichte['nrw'] = {'events': len(n), **z}
    except Exception as e:  # noqa: BLE001
        berichte['nrw'] = f'Fehler: {e}'
    # Entdoppeln (gleicher Titel + Tag + Ort): manuell > koeln > nrw
    rang = {'manuell': 0, 'koeln': 1, 'nrw': 2}
    alle.sort(key=lambda e: (rang.get(e['quelle'], 9), e['von']))
    gesehen, eindeutig = set(), []
    for e in alle:
        s = _schluessel(e)
        if s in gesehen:
            continue
        gesehen.add(s)
        eindeutig.append(e)
    eindeutig.sort(key=lambda e: (e['von'], e['titel']))
    if len(eindeutig) < 20:
        # Schutz: lieber die alte Datei behalten als eine fast leere ausliefern.
        print('Zu wenige Events – docs/events.json bleibt unverändert.', berichte)
        sys.exit(1)
    daten = {
        'version': 1,
        'stand': g.jetzt_iso(),
        'horizont_tage': HORIZONT_TAGE,
        'quellen': {
            'koeln': {'name': 'Stadt Köln – Veranstaltungskalender (Open Data)',
                      'lizenz': 'Datenlizenz Deutschland – Zero – 2.0',
                      'url': 'https://www.offenedaten-koeln.de/'},
            'nrw': {'name': 'Tourismus NRW e.V. – Open Data Hub (destination.one)',
                    'lizenz': 'je Eintrag (hier nur gemeinfrei/CC)',
                    'url': 'https://tourismusverband.nrw/open-data-finder'},
            'manuell': {'name': 'Erlebsy-Recherche (Betreiber-Websites)',
                        'lizenz': 'eigene Recherche', 'url': ''},
        },
        'bericht': berichte,
        'events': eindeutig,
    }
    pfad = g.schreibe('events.json', daten)
    print(f'{len(eindeutig)} Events → {pfad}')
    print(json.dumps(berichte, ensure_ascii=False))


if __name__ == '__main__':
    main()
