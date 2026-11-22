# erlebsy-daten

Offene Daten für die App **Erlebsy** (Familienausflüge rund um Köln/NRW).
Ein GitHub-Job (`.github/workflows/taeglich.yml`) holt täglich neue Daten und legt sie in `docs/` ab;
GitHub Pages stellt sie bereit:

| Datei | Inhalt |
|---|---|
| `docs/events.json` | kommende Familien-/Freizeit-Events (NRW, nächste 120 Tage) |
| `docs/orte.json` | Eintritt und Öffnungszeiten von Ausflugszielen (NRW) |

## Quellen und Lizenzen

- **Stadt Köln – Veranstaltungskalender** (Open Data, [offenedaten-koeln.de](https://www.offenedaten-koeln.de/)),
  Datenlizenz Deutschland – Zero – 2.0.
- **Tourismus NRW e.V. – Open Data Hub** ([Open Data Finder](https://tourismusverband.nrw/open-data-finder)),
  Daten über destination.one/eT4. Übernommen werden nur Einträge mit offener Lizenz
  (gemeinfrei, CC0, CC BY, CC BY-SA); die Lizenz steht an jedem Eintrag (`lizenz`).
- `pipeline/manuell.json`: eigene Recherche auf Betreiber-Websites (Quelle als Link je Eintrag).

Übernommen werden nur Fakten (Titel, Datum, Uhrzeit, Ort, Koordinaten, Link, Preise, Öffnungszeiten) –
keine Beschreibungstexte, keine Bilder. Angaben ohne Gewähr; bitte vor dem Besuch beim Betreiber prüfen.

## Lokal ausführen

```bash
python3 pipeline/events.py && python3 pipeline/orte.py && python3 pipeline/pruefen.py
```

Nur Python-Standardbibliothek, keine Schlüssel.
