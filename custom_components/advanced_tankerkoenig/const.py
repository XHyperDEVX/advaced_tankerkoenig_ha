"""Constants for Advanced Tankerkoenig (not the built-in integration)."""
DOMAIN = "advanced_tankerkoenig"
NAME = "Advanced Tankerkoenig"
PLATFORMS = ["sensor", "binary_sensor"]
CONF_API_KEY = "api_key"
CONF_STATIONS = "stations"
MAX_STATIONS = 10
API_BASE = "https://creativecommons.tankerkoenig.de/json"
PRICE_MIN_SECONDS = 5 * 60
PRICE_MAX_SECONDS = 10 * 60
DETAIL_MIN_SECONDS = 120 * 60 * 60
DETAIL_MAX_SECONDS = 168 * 60 * 60
DETAIL_RETRY_SECONDS = 60 * 60
FUEL_TYPES = ("diesel", "e10", "e5")
FUEL_LABELS = {"diesel": "Diesel", "e10": "E10", "e5": "E5"}
WEEKDAYS = (
    (0, "montag", "Montag"),
    (1, "dienstag", "Dienstag"),
    (2, "mittwoch", "Mittwoch"),
    (3, "donnerstag", "Donnerstag"),
    (4, "freitag", "Freitag"),
    (5, "samstag", "Samstag"),
    (6, "sonntag", "Sonntag"),
)
ATTRIBUTION = "Daten: Tankerkönig / MTS-K. Lizenz und Bedingungen: https://creativecommons.tankerkoenig.de"
