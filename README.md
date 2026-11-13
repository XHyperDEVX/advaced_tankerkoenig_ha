> **Hinweis:** Dieses Repository wurde vollständig mit KI generiert, wird nicht aktiv gepflegt und ist die Veröffentlichung eines ursprünglich für private Zwecke genutzten Projekts. Es wird ohne Gewähr bereitgestellt.

# Advanced Tankerkoenig für Home Assistant

Eine eigenständige Custom Integration für aktuelle Kraftstoffpreise und Tankstellendaten der Tankerkönig-API. Die technische Domain lautet **`advanced_tankerkoenig`**; damit besteht kein Konflikt zur eingebauten Home-Assistant-Integration `tankerkoenig`.

## Lizenz und API

Der Quellcode dieser Integration steht unter der [MIT-Lizenz](LICENSE). **Tankerkönig-API und -Daten unterliegen eigenen Lizenz- und Nutzungsbedingungen und sind nicht durch die MIT-Lizenz dieses Repositories lizenziert.** Maßgeblich sind die aktuellen Angaben des API-Anbieters sowie die Lizenzinformation der API-Antworten.

Einen API-Schlüssel gibt es unter <https://creativecommons.tankerkoenig.de>. Laut Projektangabe war die API **Stand November 2026 kostenlos**; bitte die aktuellen Bedingungen beim Anbieter prüfen.

## Installation

1. `custom_components/advanced_tankerkoenig` nach `config/custom_components/advanced_tankerkoenig` kopieren.
2. Home Assistant neu starten. Bei einem Update dieser Integration: den Eintrag einmal **neu laden** oder Home Assistant komplett neu starten, damit alte Kalender-, Informations- und Nicht-verfügbar-Entitäten aus dem Register bereinigt werden.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Advanced Tankerkoenig**.
4. Den API-Schlüssel sowie 1–10 Tankstellen-UUIDs eingeben.

Die Integration kann außerdem über HACS als benutzerdefiniertes Repository der Kategorie **Integration** installiert werden. Sie enthält keine eigene Weboberfläche und verwendet das Theme von Home Assistant, also auch dessen Darkmode.

### Umstieg von der vorherigen Custom Integration

Die frühere Custom Domain `tankerkoenig` wurde absichtlich durch `advanced_tankerkoenig` ersetzt, damit sie nicht die eingebaute Integration überlagert. Dadurch ist dies ein neuer HA-Eintrag; alte Automationen werden nicht automatisch angepasst.

1. Vorher ein HA-Backup erstellen.
2. Den alten **Custom**-Integrationseintrag entfernen und `config/custom_components/tankerkoenig` löschen. Keine Dateien der HA-Core-Integration löschen.
3. Den neuen Ordner installieren, HA neu starten und **Advanced Tankerkoenig** einrichten.
4. Dashboards und Automationen auf die neuen Entity-IDs umstellen.

Eine automatische Übernahme fremder `tankerkoenig`-Einträge erfolgt bewusst nicht, weil sie zur eingebauten Integration gehören könnten. Beide Integrationen können parallel laufen, führen dann aber getrennte API-Abrufe aus.

## Tankstellen-UUIDs und Konfiguration

Auf <https://www.tankerkoenig.de> die Station suchen und die UUID aus der URL kopieren:

`https://www.tankerkoenig.de/tankstelle/7d8ba49c-b9ec-4672-b76f-251b3065b9af`

UUID: `7d8ba49c-b9ec-4672-b76f-251b3065b9af`

- Es sind höchstens **10 eindeutige UUIDs** möglich.
- UUIDs können mit Leerzeichen, Zeilenumbrüchen, Kommas oder Semikolons getrennt werden. Ganze URLs werden absichtlich abgelehnt.
- **Eintrag hinzufügen** fragt nach der Erstkonfiguration nur nach neuen UUIDs. Der vorhandene API-Schlüssel wird verwendet; es entsteht weder ein zweiter API-Zugang noch ein zweites Übersichtsgerät.
- **Konfigurieren** bearbeitet die vollständige UUID-Liste.
- **Neu konfigurieren** ersetzt den einen gespeicherten API-Schlüssel.

Geräte für neue Stationen erscheinen nach ihrem erfolgreichen Detailabruf. Ein Detailfehler einer UUID blockiert weder andere Stationen noch den gemeinsamen Preisabruf.

## Geräte, Namen und Entity-IDs

Jede Station ist ein eigenes Gerät. Der Standardname enthält Name, Straße/Hausnummer und Ort, beispielsweise **`Aral – Müllerallee 12, Berlin`**. Manuell vergebene Gerätenamen werden nicht überschrieben.

Entitäten erhalten pro Station ein stabiles, ortsbasiertes Präfix, zum Beispiel:

- `sensor.advanced_tankerkoenig_berlin1_e5_preis`
- `sensor.advanced_tankerkoenig_berlin1_montag_oeffnungszeiten`
- `binary_sensor.advanced_tankerkoenig_berlin1_geoeffnet`

Die zweite Station im gleichen Ort erhält `berlin2`; Umlaute werden umgeschrieben (`muenchen1`). Die UUID→Präfix-Zuordnung wird persistent gespeichert und nie umnummeriert. Eigene Änderungen an einer Entity-ID im HA-Entity-Register bleiben erhalten.

## Entitäten je Tankstelle

| Anzeige | Typ | Verhalten |
| --- | --- | --- |
| Diesel / E10 / E5 Preis | `sensor`, Messwert, €/L | Aktuelle bzw. bei `closed` zuletzt bekannte Preise. |
| Tankstellenname | `binary_sensor`, Device Class `opening` | **Einziger** aktueller Öffnungsstatus. Der Anzeigename entspricht dem Gerätenamen. |
| 24/7 geöffnet | `binary_sensor` | Wert des API-Felds `wholeDay`. |
| Öffnet/Schließt | `sensor`, Timestamp | Nächster berechenbarer Wechsel; Attribut `aktion` ist `öffnet` oder `schließt`. |
| Montag bis Sonntag Öffnungszeiten | je ein `sensor` | Je Wochentag ein Zeitbereich wie `06:00–12:00, 14:00–22:00`; strukturierte Zeiträume liegen im Attribut `zeitraeume`. |
| Besondere Öffnungszeiten | `sensor` | Nur bei tatsächlich vorhandenen Ausnahmen; vollständige Texte im Attribut `eintraege`. |
| Standort | `sensor` | Ort als Zustand; Standardattribute `latitude` und `longitude` bündeln die Koordinaten. |

Die früheren Entitäten **Tankstelleninformationen**, **Nicht verfügbar** und der doppelte Detail-Öffnungsstatus wurden entfernt. Fehlende Kraftstoffpreise machen direkt die jeweilige Preisentität nicht verfügbar. Alle vorhandenen `quelle`-Attribute enthalten einheitlich **`Tankerkoenig`**.

### Reguläre Öffnungszeiten und 24/7

Die API liefert einen Wochenplan; Home Assistants `schedule` ist dagegen ein lokal bearbeitbarer Helfer und keine öffentliche read-only Plattform für externe Daten. Deshalb stellt die Integration den Plan als sieben klare Wochentag-Sensoren bereit. Mehrteilige Öffnungen, Nachtöffnungen und `24:00` werden berücksichtigt. Jeder Sensor beschreibt ausschließlich die **regulären** Öffnungszeiten seines Wochentags; Sonderöffnungszeiten können abweichen.

Bei `wholeDay: true` gibt es keine Wochentag-Sensoren, keine `Öffnet/Schließt`-Entität und keine Sonderöffnungszeiten-Entität. Der Öffnungs-Binary-Sensor bleibt aber ausdrücklich vorhanden und ist **ein**, ebenso der 24/7-Indikator, Preise und Standort.

`Öffnet/Schließt` berechnet den nächsten Wechsel in `Europe/Berlin` und aktualisiert sich lokal ohne zusätzliche API-Anfrage. Exakte Datumsbereich-Ausnahmen werden einbezogen. Zusammengesetzte API-Texte wie `Samstag, Sonntag, Feiertag` liefern korrekt die regulären Samstag-/Sonntag-Zeiten; der nicht als Wochentag modellierbare Feiertagszusatz wird über das Attribut `vollstaendig_interpretierbar: false` beziehungsweise `hinweis` transparent gemacht. Fehlt ein lesbarer Wochenplan vollständig, bleibt sie unbekannt, weil kein Wechsel seriös erfunden werden kann.

## Übersichtsgerät

**Advanced Tankerkoenig Übersicht** enthält:

- den Zeitpunkt des letzten erfolgreichen Preis- und Detailabrufs,
- den günstigsten Diesel-, E10- und E5-Preis,
- je eine Entität für die günstigste Tankstelle je Kraftstoff mit Adresse, Koordinaten und Preis als Attributen.

Die API kennt die Kraftstofftypen **Diesel**, **E10** und **E5**; E5 entspricht dem gewünschten Super-Benzin-Sensor, nicht „R5“. Preisgleichstände werden stabil über die UUID aufgelöst.

## Abrufe, Cache und Fehlerverhalten

- **Preise:** Ein gemeinsamer `prices.php`-Abruf für alle eingerichteten UUIDs; der nächste Zeitpunkt wird nach jedem Durchlauf zufällig zwischen **5 und 10 Minuten** gewählt.
- **Details:** Ein separater `detail.php`-Aufruf und Timer pro Station. Nach Erfolg beträgt das zufällige Intervall **120–168 Stunden**; nach Fehlern wird nach einer Stunde erneut versucht.
- Timer, Detaildaten, Preis-Cache und Entity-Präfixe werden persistent gespeichert. Ein Neustart erzeugt keine überflüssigen Abrufe.
- `ok != true`: Daten werden nicht übernommen. Die API-`message` erscheint in Home Assistant und im Protokoll, ohne Request-URL/API-Schlüssel zu übernehmen.
- `no prices`: alle drei Preisentitäten der betroffenen Station sind vorübergehend nicht verfügbar und HA meldet den Fehler. Der nächste gemeinsame Abruf versucht die Wiederherstellung.
- `e5: false` (analog E10/Diesel): nur diese Preisentität wird ohne Zusatzfehler nicht verfügbar.
- `closed`: bekannte Preise bleiben unverändert; es wird kein Preis erfunden.
- Preis-/Netzfehler: Werte werden bis zum nächsten Erfolg in HA als nicht verfügbar behandelt. Detailfehler anderer Stationen beeinflussen sie nicht.
- Beim Entladen/Beenden werden Timer und laufende Tasks beendet. Die Registry-Bereinigung betrifft nur `advanced_tankerkoenig`.

Verwendete Endpunkte:

- `https://creativecommons.tankerkoenig.de/json/prices.php`
- `https://creativecommons.tankerkoenig.de/json/detail.php`


Dieses Projekt ist unabhängig von Tankerkönig und wird weder vom API-Anbieter noch vom Home-Assistant-Projekt bereitgestellt oder unterstützt.
