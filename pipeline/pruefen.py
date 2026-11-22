#!/usr/bin/env python3
"""Plausibilitätsprüfung vor dem Veröffentlichen (bricht bei Fehlern ab)."""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemeinsam as g  # noqa: E402

fehler = []
ev = json.load(open(os.path.join(g.AUSGABE, 'events.json'), encoding='utf-8'))
if ev.get('version') != 1 or len(ev.get('events', [])) < 20:
    fehler.append('events.json: Version/Anzahl unplausibel')
for e in ev.get('events', []):
    try:
        dt.date.fromisoformat(e['von'])
        if e.get('bis'):
            dt.date.fromisoformat(e['bis'])
    except (KeyError, ValueError):
        fehler.append(f'events.json: Datum kaputt bei {e.get("titel")}')
        break
    if not e.get('titel') or not e.get('quelle'):
        fehler.append('events.json: Titel/Quelle fehlt')
        break
orte = json.load(open(os.path.join(g.AUSGABE, 'orte.json'), encoding='utf-8'))
if orte.get('version') != 1 or len(orte.get('orte', [])) < 500:
    fehler.append('orte.json: Version/Anzahl unplausibel')
for o in orte.get('orte', []):
    p = o.get('preis') or {}
    for k in ('erw', 'kind', 'familie'):
        if k in p and not (0 <= p[k] <= 500):
            fehler.append(f'orte.json: Preis unplausibel bei {o["name"]}')
if fehler:
    print('\n'.join(fehler))
    sys.exit(1)
print(f'ok: {len(ev["events"])} Events, {len(orte["orte"])} Orte')
