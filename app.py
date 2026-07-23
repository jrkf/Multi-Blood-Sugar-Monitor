"""
Monitor cukru dla dzieci na obozie - podglad odczytow Dexcom, LibreLinkUp, Nightscout i CareLink.
"""

import hashlib
import json
import os
import threading
import time
import uuid
import carelink_client2
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, redirect, url_for, session

try:
    from pydexcom import Dexcom
except ImportError:
    Dexcom = None

try:
    import requests
except ImportError:
    requests = None

# --- INTEGRACJA CARELINK ---
try:
    import carelink_client2
except ImportError:
    carelink_client2 = None

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "static", "sounds")
ALLOWED_SOUND_EXT = {".wav", ".mp3", ".ogg"}

DEFAULT_CONFIG = {
    "config_password": "zmien_haslo",
    "polling_interval_seconds": 60,
    "columns": 6,
    "window_width": 220,
    "window_height": 150,
    "card_font_scale": 100,
    "patients": [],
    "groups": [],
    "threshold_low": 70,
    "threshold_high": 180,
    "alert_repeat_seconds": 15,
    "sound_low_file": "default_low.wav",
    "sound_high_file": "default_high.wav",
}

app = Flask(__name__)
app.secret_key = "cukrzyca-monitor-" + str(uuid.uuid4())

readings_lock = threading.Lock()
readings_cache = {}
config_lock = threading.RLock()


def load_config():
    with config_lock:
        if not os.path.exists(CONFIG_PATH):
            save_config(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for key, value in DEFAULT_CONFIG.items():
            cfg.setdefault(key, value)
        return cfg


def save_config(cfg):
    with config_lock:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_or_create_group_id(cfg, group_name):
    """Zwraca id grupy o podanej nazwie, tworzac ja jesli jeszcze nie istnieje."""
    group_name = (group_name or "").strip()
    if not group_name:
        return ""
    cfg.setdefault("groups", [])
    for g in cfg["groups"]:
        if g["name"].lower() == group_name.lower():
            return g["id"]
    new_id = str(uuid.uuid4())
    cfg["groups"].append({"id": new_id, "name": group_name})
    return new_id


def classify_glucose(value, threshold_low=70, threshold_high=180):
    if value is None:
        return "unknown"
    if value < threshold_low:
        return "low"
    if value > threshold_high:
        return "high"
    return "normal"


NS_TREND_ARROWS = {1: "↑↑", 2: "↑", 3: "↗", 4: "→", 5: "↘", 6: "↓", 7: "↓↓"}

# Niektore systemy (np. Nightscout, Dexcom) czasem zwracaja trend jako tekst
# ("Flat", "DoubleDown" itp.) zamiast gotowej strzalki - ta mapa zamienia
# wszystkie znane warianty tekstowe na jednolite strzalki, tak samo jak
# w innych zrodlach danych.
TREND_TEXT_TO_ARROW = {
    "doubleup": "↑↑", "singleup": "↑", "fortyfiveup": "↗", "slightup": "↗",
    "flat": "→", "stable": "→", "none": "→",
    "fortyfivedown": "↘", "slightdown": "↘",
    "singledown": "↓", "doubledown": "↓↓",
    "notcomputable": "", "rateoutofrange": "",
}

# Powyzej ktorego wieku odczytu (w sekundach) uznajemy dane za nieaktualne
# i przestajemy pokazywac cyfre cukru na kafelku (pokazujemy tylko "--" + info o wieku odczytu).
STALE_AFTER_SECONDS = 15 * 60


def _age_seconds_from_utc(reading_dt_utc):
    """Liczy wiek odczytu w sekundach na podstawie znacznika czasu ze
    swiadomoscia strefy (tzinfo=UTC), porownujac go z aktualnym czasem UTC.
    Dzieki temu wynik jest poprawny niezaleznie od tego, w jakiej strefie
    czasowej dziala komputer/serwer, na ktorym uruchomiony jest monitor -
    w przeciwienstwie do wczesniejszego porownywania "naiwnych" (bez strefy)
    znacznikow czasu z datetime.now()."""
    if reading_dt_utc is None:
        return None
    return (datetime.now(timezone.utc) - reading_dt_utc).total_seconds()


def parse_llu_factory_timestamp_utc(ts_str):
    """Parsuje pole 'FactoryTimestamp' z LibreLinkUp API.

    UWAGA NA STREFY CZASOWE: LibreLinkUp zwraca DWA znaczniki czasu -
    'Timestamp' oraz 'FactoryTimestamp'. 'Timestamp' bywa przesuniety w
    niestandardowy sposob (zalezny od ustawien konta/regionu) i NIE
    odpowiada wprost ani czasowi lokalnemu komputera z monitorem, ani
    czystemu UTC - dlatego nie nadaje sie do liczenia wieku odczytu.
    'FactoryTimestamp' jest za to zawsze czasem UTC, wiec to jego uzywamy
    do wyliczenia, czy odczyt jest starszy niz STALE_AFTER_SECONDS. Do
    wyswietlenia godziny na kafelku nadal uzywamy pola 'Timestamp' (zeby nie
    zmieniac tego, co widzi uzytkownik) - zmienia sie tylko logika
    "czy pokazac/schowac wartosc".
    """
    if not ts_str:
        return None
    try:
        naive_utc = datetime.strptime(ts_str, "%m/%d/%Y %I:%M:%S %p")
        return naive_utc.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_carelink_timestamp_utc(raw_ts):
    """Parsuje znacznik czasu odczytu z CareLink na obiekt datetime ze
    swiadomoscia strefy czasowej (zawsze sprowadzony do UTC).

    CareLink potrafi zwrocic czas w kilku wariantach: z sufiksem 'Z' (UTC),
    z jawnym przesunieciem np. '+02:00', albo bez zadnej informacji o
    strefie. Poprzednia wersja kodu po prostu obcinala wszystko po '+' lub
    'Z' i traktowala pozostaly czas jako czas lokalny komputera z
    monitorem - to byl blad: np. czas z sufiksem 'Z' (UTC) byl traktowany
    tak, jakby byl juz czasem polskim, co przy roznicy stref (UTC+1/UTC+2)
    powodowalo, ze swiezy odczyt wygladal na 1-2h starszy niz w
    rzeczywistosci (i byl niepotrzebnie ukrywany jako "nieaktualny").
    Teraz jawnie parsujemy strefe i sprowadzamy wszystko do UTC, dzieki
    czemu porownanie wieku odczytu jest poprawne niezaleznie od strefy
    czasowej komputera, na ktorym dziala monitor.
    """
    if not raw_ts:
        return None
    ts = raw_ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            # Brak jawnej strefy w danych z CareLink - w praktyce dane bez
            # strefy z tego API sa czasem UTC, wiec przyjmujemy UTC zamiast
            # (blednie) zakladac czas lokalny komputera z monitorem.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def normalize_trend_arrow(raw_arrow):
    """Zwraca gotowa strzalke (↑↑ ↑ ↗ → ↘ ↓ ↓↓) niezaleznie od tego, czy zrodlo
    danych zwrocilo juz strzalke, czy tekstowy opis trendu ("Flat", "DoubleDown"...)."""
    if not raw_arrow:
        return ""
    if raw_arrow in ("↑↑", "↑", "↗", "→", "↘", "↓", "↓↓"):
        return raw_arrow
    key = str(raw_arrow).strip().lower().replace(" ", "").replace("_", "")
    return TREND_TEXT_TO_ARROW.get(key, "")


def build_stale_result(pid, name, time_str, age_seconds):
    """Wynik dla odczytu starszego niz STALE_AFTER_SECONDS - ukrywa wartosc cukru."""
    age_minutes = int(age_seconds // 60)
    return {
        "id": pid, "name": name, "value": None, "trend_arrow": "",
        "trend_description": "", "time": time_str, "status": "stale",
        "error": f"Nieaktualne dane - ostatni odczyt sprzed {age_minutes} min",
        "category": "stale",
    }

# --- LibreLinkUp ---
LLU_REGION_HOSTS = {
    "eu": "api-eu.libreview.io", "us": "api-us.libreview.io", "de": "api-de.libreview.io",
    "fr": "api-fr.libreview.io", "jp": "api-jp.libreview.io", "ap": "api-ap.libreview.io",
    "au": "api-au.libreview.io", "ca": "api-ca.libreview.io", "ae": "api-ae.libreview.io"
}
LLU_VERSION = "4.16.0"
LLU_TREND_ARROWS = {1: "↓↓", 2: "↓", 3: "→", 4: "↑", 5: "↑↑"}

llu_session_lock = threading.Lock()
llu_session_cache = {}


def _llu_headers(token=None, account_id_hash=None):
    headers = {
        "Content-Type": "application/json",
        "product": "llu.android",
        "version": LLU_VERSION,
        "Accept-Encoding": "gzip",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if account_id_hash:
        headers["Account-Id"] = account_id_hash
    return headers


def _llu_login(email, password, region):
    host = LLU_REGION_HOSTS.get(region, LLU_REGION_HOSTS["eu"])
    resp = requests.post(
        f"https://{host}/llu/auth/login",
        json={"email": email, "password": password},
        headers=_llu_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    redirect_region = (payload.get("data") or {}).get("redirect") and payload["data"].get("region")
    if redirect_region and redirect_region in LLU_REGION_HOSTS and redirect_region != region:
        return _llu_login(email, password, redirect_region)
    
    auth_ticket = payload.get("data", {}).get("authTicket", {})
    token = auth_ticket.get("token")
    user_id = auth_ticket.get("user")
    
    if not token or not user_id:
        token = payload["data"]["authTicket"]["token"]
        user_id = payload["data"]["user"]["id"]

    account_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return token, account_id_hash, host


def _llu_get_session(patient):
    pid = patient["id"]
    with llu_session_lock:
        cached = llu_session_cache.get(pid)
        if cached and cached["expires"] > time.time():
            return cached["token"], cached["account_id_hash"], cached["host"]
    token, account_id_hash, host = _llu_login(
        patient["librelinkup_email"],
        patient["librelinkup_password"],
        patient.get("librelinkup_region", "eu"),
    )
    with llu_session_lock:
        llu_session_cache[pid] = {
            "token": token,
            "account_id_hash": account_id_hash,
            "host": host,
            "expires": time.time() + 3600,
        }
    return token, account_id_hash, host


def fetch_one_patient_librelinkup(patient, threshold_low=70, threshold_high=180):
    pid = patient["id"]
    name = patient.get("name", "?")
    if requests is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki requests (pip install requests)", "category": "unknown",
        }
    try:
        try:
            token, account_id_hash, host = _llu_get_session(patient)
        except Exception:
            with llu_session_lock:
                llu_session_cache.pop(pid, None)
            token, account_id_hash, host = _llu_get_session(patient)

        headers = _llu_headers(token, account_id_hash)
        configured_patient_id = (patient.get("librelinkup_patient_id") or "").strip()

        conn_resp = requests.get(f"https://{host}/llu/connections", headers=headers, timeout=10)
        conn_resp.raise_for_status()
        connections = (conn_resp.json() or {}).get("data", [])
        if not connections:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": "Brak dzieci powiazanych z tym kontem LibreLinkUp", "category": "unknown",
            }

        available = [
            {"patientId": c.get("patientId"), "name": (c.get("firstName", "") + " " + c.get("lastName", "")).strip()}
            for c in connections
        ]

        target_patient_id = configured_patient_id
        if configured_patient_id and not any(c["patientId"] == configured_patient_id for c in available):
            target_patient_id = available[0]["patientId"]
        elif not configured_patient_id:
            target_patient_id = available[0]["patientId"]

        graph_resp = requests.get(
            f"https://{host}/llu/connections/{target_patient_id}/graph", headers=headers, timeout=10
        )
        graph_resp.raise_for_status()
        gdata = (graph_resp.json() or {}).get("data", {})
        point = (gdata.get("connection") or {}).get("glucoseMeasurement")
        if not point:
            graph_list = gdata.get("graphData") or []
            point = graph_list[-1] if graph_list else None
        if not point:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": "Brak aktualnych danych (sensor offline?)", "category": "unknown",
            }
        value = point.get("Value") if point.get("Value") is not None else point.get("value")
        trend = point.get("TrendArrow") if point.get("TrendArrow") is not None else point.get("trendArrow")
        arrow = normalize_trend_arrow(LLU_TREND_ARROWS.get(trend, ""))
        ts_str = point.get("Timestamp") or point.get("FactoryTimestamp")
        time_str = None
        if ts_str:
            try:
                time_str = datetime.strptime(ts_str, "%m/%d/%Y %I:%M:%S %p").strftime("%H:%M:%S")
            except ValueError:
                time_str = None

        # Do liczenia wieku odczytu uzywamy FactoryTimestamp (zawsze UTC),
        # a nie Timestamp - patrz komentarz w parse_llu_factory_timestamp_utc.
        reading_dt_utc = parse_llu_factory_timestamp_utc(point.get("FactoryTimestamp"))
        age_seconds = _age_seconds_from_utc(reading_dt_utc)
        if age_seconds is not None and age_seconds > STALE_AFTER_SECONDS:
            return build_stale_result(pid, name, time_str, age_seconds)

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": time_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error", "error": f"{exc}",
            "category": "unknown",
        }


def fetch_one_patient_nightscout(patient, threshold_low=70, threshold_high=180):
    pid = patient["id"]
    name = patient.get("name", "?")
    if requests is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki requests (pip install requests)", "category": "unknown",
        }
    url = (patient.get("nightscout_url") or "").rstrip("/")
    if not url:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak adresu URL Nightscout", "category": "unknown",
        }
    try:
        params = {"count": 1}
        token = patient.get("nightscout_token")
        if token:
            params["token"] = token
        resp = requests.get(f"{url}/api/v1/entries.json", params=params, timeout=10)
        resp.raise_for_status()
        entries = resp.json()
        if not entries:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": "Brak aktualnych danych (sensor offline?)", "category": "unknown",
            }
        entry = entries[0]
        value = entry.get("sgv")
        trend = entry.get("trend")
        direction = entry.get("direction", "") or ""
        arrow = NS_TREND_ARROWS.get(trend)
        if arrow is None:
            arrow = normalize_trend_arrow(direction)
        ts_ms = entry.get("date")
        time_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S") if ts_ms else None

        # Nightscout zawsze zwraca "ostatni jaki ma" wpis, nawet sprzed wielu godzin,
        # jesli sensor/telefon przestal wysylac dane. Sprawdzamy wiek odczytu i jesli
        # jest starszy niz STALE_AFTER_SECONDS, ukrywamy wartosc cukru (kafelek "stale"),
        # zamiast pokazywac ewentualnie mylaca, nieaktualna liczbe.
        age_seconds = (time.time() - ts_ms / 1000) if ts_ms else None
        if age_seconds is not None and age_seconds > STALE_AFTER_SECONDS:
            return build_stale_result(pid, name, time_str, age_seconds)

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": direction, "time": time_str,
            "status": "ok", "error": None, "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad polaczenia z Nightscout: {exc}", "category": "unknown",
        }

# --- NOWA FUNKCJA: CareLink ---
CARELINK_TREND_ARROWS = {
    "DOUBLE_UP": "↑↑", "SINGLE_UP": "↑", "SLIGHT_UP": "↗",
    "STABLE": "→", "SLIGHT_DOWN": "↘", "SINGLE_DOWN": "↓", "DOUBLE_DOWN": "↓↓",
    # Medtronic w polu "lastSGTrend" zwraca czesto krotsze nazwy - dopisujemy alias
    "UP": "↑", "DOWN": "↓", "FLAT": "→", "NONE": "→", "NOT_COMPUTABLE": "→",
}

def fetch_one_patient_carelink(patient, threshold_low=70, threshold_high=180):
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    raw_token_file = patient.get("carelink_token_file", "").strip()
    if not raw_token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }

    # --- ZMIANA ŚCIEŻKI DO FOLDERU json_files ---
    # Pobiera samą nazwę pliku z ciągu i dokleja folder "json_files"
    filename_only = os.path.basename(raw_token_file)
    token_file = os.path.join("json_files", filename_only)
    # ---------------------------------------------
    try:
        # Inicjalizacja klienta
        client = carelink_client2.CareLinkClient(tokenFile=token_file)
        
        if not client.init():
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Blad inicjalizacji klienta CareLink (sprawdz plik tokenu)", "category": "unknown",
            }
        
        raw_data = client.getRecentData()
        if not raw_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }

        # UWAGA: sg/lastSG/lastSGTrend siedza wewnatrz "patientData", nie na najwyzszym
        # poziomie odpowiedzi - getRecentData() zwraca {"metadata": ..., "patientData": {...}}
        recent_data = raw_data.get("patientData", raw_data)

        last_sg = recent_data.get("lastSG", {})
        value = last_sg.get("sg")

        # Pobieranie strzałki trendu
        arrow = "→"
        if "rateOfChange" in recent_data:
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
        elif "lastSGTrend" in recent_data:
            roc = recent_data.get("lastSGTrend", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
        arrow = normalize_trend_arrow(arrow) or "→"

        # Wyciąganie czasu z pola 'timestamp' (zachowujemy pelna wersje do liczenia wieku odczytu)
        raw_ts = last_sg.get("timestamp")
        ts_str = raw_ts or datetime.now().strftime("%H:%M:%S")
        # Parsujemy z uwzglednieniem strefy czasowej (patrz komentarz w
        # parse_carelink_timestamp_utc) - poprzednio strefa byla po prostu
        # obcinana, co przy odczytach w UTC ('Z') dawalo bledny (zawyzony
        # o wartosc przesuniecia strefy) wiek odczytu.
        reading_dt_utc = parse_carelink_timestamp_utc(raw_ts)
        if "T" in ts_str:
            try:
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        # OBSŁUGA CHWILOWEGO BRAKU ODRAZU Z SENSORA (np. kalibracja)
        if value is None:
            return {
                "id": pid,
                "name": name,
                "value": "---",           # Wyświetli kreski zamiast pustego błędu
                "trend_arrow": "",
                "trend_description": "Oczekiwanie na sensor / Kalibracja",
                "time": ts_str,
                "status": "ok",           # Zmieniamy na "ok", żeby traktować to jako normalny stan pompy
                "error": None,
                "category": "unknown",
            }

        age_seconds = _age_seconds_from_utc(reading_dt_utc)
        if age_seconds is not None and age_seconds > STALE_AFTER_SECONDS:
            return build_stale_result(pid, name, ts_str, age_seconds)

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    token_file = patient.get("carelink_token_file", "").strip()
    if not token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }
    try:
        # Inicjalizacja klienta z plikiem tokenu przekazanym do konstruktora
        client = carelink_client2.CareLinkClient(tokenFile=token_file)
        
        # Wywołanie init() bez argumentów
        if not client.init():
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Blad inicjalizacji klienta CareLink (sprawdz plik tokenu)", "category": "unknown",
            }
        
        # Pobieranie danych z serwera Medtronic
        recent_data = client.getRecentData()
        if not recent_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }
            
        # Dostosowanie do rzeczywistej struktury JSON (lastSG -> sg)
        last_sg = recent_data.get("lastSG", {})
        value = last_sg.get("sg")
        
        if value is None:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": "Otrzymano pusty obiekt glikemii z CareLink (brak parametru sg)", "category": "unknown",
            }

        # Wyznaczanie strzałki trendu glikemii
        arrow = "→"
        if "rateOfChange" in recent_data:
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
        elif "lastSGTrend" in recent_data:
            roc = recent_data.get("lastSGTrend", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
            
        # Wyciąganie poprawnego czasu z pola 'timestamp'
        ts_str = last_sg.get("timestamp") or datetime.now().strftime("%H:%M:%S")
        if "T" in ts_str:
            try:
                # Parsowanie formatu YYYY-MM-DDT%H:%M:%S do samej godziny HH:MM:SS
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    token_file = patient.get("carelink_token_file", "").strip()
    if not token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }
    try:
        # Prawidłowa inicjalizacja dla nowej wersji biblioteki:
        # Ścieżkę do pliku przekazujemy w konstruktorze obiektu
        client = carelink_client2.CareLinkClient(tokenFile=token_file)
        
        # Metodę init() wywołujemy już bez żadnych argumentów
        if not client.init():
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Blad inicjalizacji klienta CareLink (sprawdz plik tokenu)", "category": "unknown",
            }
        
        # Pobieramy dane z serwera Medtronic
        recent_data = client.getRecentData()
        if not recent_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }
            
        value = recent_data.get("lastBG", {}).get("value")
        arrow = "→"
        if "rateOfChange" in recent_data:
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
            
        ts_str = recent_data.get("lastBG", {}).get("datetime") or datetime.now().strftime("%H:%M:%S")
        if "T" in ts_str:
            try:
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    token_file = patient.get("carelink_token_file", "").strip()
    if not token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }
    try:
        # ZGODNIE Z NOWYM STANDARDEM CLI:
        # 1. Tworzymy czysty obiekt klienta bez przekazywania argumentów do konstruktora
        client = carelink_client2.CareLinkClient()
        
        # 2. Przekazujemy ścieżkę do pliku logindata.json bezpośrednio do metody init
        if not client.init(tokenFile=token_file):
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Blad inicjalizacji klienta CareLink (sprawdz plik tokenu)", "category": "unknown",
            }
        
        # 3. Pobieramy świeże dane z serwera Medtronic
        recent_data = client.getRecentData()
        if not recent_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }
            
        value = recent_data.get("lastBG", {}).get("value")
        arrow = "→"
        if "rateOfChange" in recent_data:
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
            
        ts_str = recent_data.get("lastBG", {}).get("datetime") or datetime.now().strftime("%H:%M:%S")
        if "T" in ts_str:
            try:
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    token_file = patient.get("carelink_token_file", "").strip()
    if not token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }
    try:
        # 1. Ręcznie wczytujemy JSON z Twojego pliku accessToken.json
        with open(token_file, "r", encoding="utf-8") as f:
            raw_content = f.read().strip()
            # Obsługa sytuacji, gdyby w pliku były pojedyncze cudzysłowy zamiast podwójnych
            raw_content = raw_content.replace("'", '"')
            token_data = json.loads(raw_content)
            
        # 2. Wyciągamy tokeny
        acc_token = token_data.get("access_token")
        ref_token = token_data.get("refresh_token")
        
        if not acc_token:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Plik tokenu nie zawiera klucza access_token", "category": "unknown",
            }

        # 3. Tworzymy klienta i ręcznie ustawiamy flagi autoryzacji
        client = carelink_client2.CareLinkClient(tokenFile=token_file)
        client.accessToken = acc_token
        client.refreshToken = ref_token
        client.authenticated = True  # Omijamy wywołanie client.init()
        
        # --- POPRAWKA DLA KONT CAREPARTNER (OPIEKUNA) ---
        # Pobieramy listę podopiecznych powiązanych z Twoim kontem
        try:
            philippines = client.getPatients() # Ta funkcja zwraca listę pacjentów
            if philippines and len(philippines) > 0:
                # Wybieramy pierwsze dziecko z listy i ustawiamy jako aktywny profil
                client.patientId = philippines[0].get("username")
        except Exception:
            pass # Jeśli to zwykłe konto pacjenta, funkcja może nie istnieć lub rzucić błąd - idziemy dalej
        # -----------------------------------------------
        
        # 4. Pobieramy dane z serwera Medtronic
        recent_data = client.getRecentData()
        if not recent_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }
            
        value = recent_data.get("lastBG", {}).get("value")
        arrow = "→"
        if "rateOfChange" in recent_data:
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
            
        ts_str = recent_data.get("lastBG", {}).get("datetime") or datetime.now().strftime("%H:%M:%S")
        if "T" in ts_str:
            try:
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }
    pid = patient["id"]
    name = patient.get("name", "?")
    if carelink_client2 is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki carelink_client2 (zainstaluj z github)", "category": "unknown",
        }
    token_file = patient.get("carelink_token_file", "").strip()
    if not token_file:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Nie podano sciezki do pliku tokenu CareLink", "category": "unknown",
        }
    try:
        client = carelink_client2.CareLinkClient(tokenFile=token_file)
        if not client.init():
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "error",
                "error": "Blad inicjalizacji klienta CareLink (sprawdz plik tokenu)", "category": "unknown",
            }
        
        recent_data = client.getRecentData()
        if not recent_data or client.getLastResponseCode() != 200:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": f"Brak danych z CareLink (kod: {client.getLastResponseCode()})", "category": "unknown",
            }
            
        value = recent_data.get("lastBG", {}).get("value")
        trend_str = recent_data.get("conduitStatus", {}).get(" some_trend_key_maybe ") # API zwraca rozne struktury w zaleznosci od wersji
        # W nowym carelink_client2 najpewniejsze dane o cukrze i strzalce sa w słowniku:
        # sgv lub lastSGV/lastBG
        arrow = "→"
        if "rateOfChange" in recent_data:
            # Szybka interpretacja trendu z Medtronic
            roc = recent_data.get("rateOfChange", "STABLE")
            arrow = CARELINK_TREND_ARROWS.get(roc, "→")
            
        # Wyciaganie czasu
        ts_str = recent_data.get("lastBG", {}).get("datetime") or datetime.now().strftime("%H:%M:%S")
        if "T" in ts_str:
            try:
                ts_str = ts_str.split("T")[1][:8]
            except Exception:
                pass

        return {
            "id": pid, "name": name, "value": value, "trend_arrow": arrow,
            "trend_description": "", "time": ts_str, "status": "ok", "error": None,
            "category": classify_glucose(value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad CareLink: {exc}", "category": "unknown",
        }


def fetch_one_patient(patient, threshold_low=70, threshold_high=180):
    source = patient.get("source", "dexcom")
    if source == "nightscout":
        return fetch_one_patient_nightscout(patient, threshold_low, threshold_high)
    if source == "librelinkup":
        return fetch_one_patient_librelinkup(patient, threshold_low, threshold_high)
    if source == "carelink":
        return fetch_one_patient_carelink(patient, threshold_low, threshold_high)
        
    pid = patient["id"]
    name = patient.get("name", "?")
    if Dexcom is None:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": "Brak biblioteki pydexcom (pip install pydexcom)", "category": "unknown",
        }
    try:
        dexcom = Dexcom(
            username=patient["login"], password=patient["password"], region=patient.get("region", "ous"),
        )
        reading = dexcom.get_current_glucose_reading()
        if reading is None:
            return {
                "id": pid, "name": name, "value": None, "trend_arrow": "",
                "trend_description": "", "time": None, "status": "no_data",
                "error": "Brak aktualnych danych (sensor offline?)", "category": "unknown",
            }
        time_str = reading.datetime.strftime("%H:%M:%S")
        reading_dt = reading.datetime
        if reading_dt.tzinfo is not None:
            # Nowsze wersje pydexcom zwracaja reading.datetime ze
            # swiadomoscia strefy czasowej (offset wziety z pola 'DT'
            # zwracanego przez Dexcom Share API). Nie mozna go odjac
            # bezposrednio od naiwnego datetime.now() - to powodowalo blad
            # "can't subtract offset-naive and offset-aware datetimes".
            # Sprowadzamy obie strony do UTC przed odejmowaniem.
            age_seconds = (datetime.now(timezone.utc) - reading_dt.astimezone(timezone.utc)).total_seconds()
        else:
            age_seconds = (datetime.now() - reading_dt).total_seconds()
        if age_seconds > STALE_AFTER_SECONDS:
            return build_stale_result(pid, name, time_str, age_seconds)
        arrow = normalize_trend_arrow(reading.trend_arrow) or normalize_trend_arrow(reading.trend_description)
        return {
            "id": pid, "name": name, "value": reading.value, "trend_arrow": arrow,
            "trend_description": reading.trend_description, "time": time_str,
            "status": "ok", "error": None, "category": classify_glucose(reading.value, threshold_low, threshold_high),
        }
    except Exception as exc:
        return {
            "id": pid, "name": name, "value": None, "trend_arrow": "",
            "trend_description": "", "time": None, "status": "error",
            "error": f"Blad polaczenia z Dexcom: {exc}", "category": "unknown",
        }


def polling_loop():
    while True:
        cfg = load_config()
        patients = cfg.get("patients", [])
        interval = max(30, int(cfg.get("polling_interval_seconds", 60)))
        t_low = cfg.get("threshold_low", 70)
        t_high = cfg.get("threshold_high", 180)
        for patient in patients:
            result = fetch_one_patient(patient, t_low, t_high)
            result["updated_at"] = datetime.now().strftime("%H:%M:%S")
            with readings_lock:
                readings_cache[patient["id"]] = result
        time.sleep(interval)


@app.route("/")
def dashboard():
    cfg = load_config()
    return render_template(
        "dashboard.html", columns=cfg.get("columns", 6), window_width=cfg.get("window_width", 220),
        window_height=cfg.get("window_height", 150), patient_count=len(cfg.get("patients", [])),
        sound_low_url=url_for("static", filename="sounds/" + cfg.get("sound_low_file", "default_low.wav")),
        sound_high_url=url_for("static", filename="sounds/" + cfg.get("sound_high_file", "default_high.wav")),
        alert_repeat_seconds=cfg.get("alert_repeat_seconds", 15),
        groups=cfg.get("groups", []),
        card_font_scale=cfg.get("card_font_scale", 100),
    )


@app.route("/data")
def data():
    cfg = load_config()
    order = [p["id"] for p in cfg.get("patients", [])]
    names = {p["id"]: p.get("name", "?") for p in cfg.get("patients", [])}
    group_ids = {p["id"]: p.get("group_id", "") for p in cfg.get("patients", [])}
    sources = {p["id"]: p.get("source", "dexcom") for p in cfg.get("patients", [])}
    with readings_lock:
        out = []
        for pid in order:
            item = readings_cache.get(pid, {
                "id": pid, "name": names.get(pid, "?"), "value": None,
                "trend_arrow": "", "status": "waiting", "error": "Oczekiwanie na pierwszy odczyt...",
                "category": "unknown", "time": None, "updated_at": None,
            })
            item = dict(item)
            item["group_id"] = group_ids.get(pid, "")
            item["source"] = sources.get(pid, "dexcom")
            out.append(item)
    return jsonify(out)


def require_login():
    return session.get("logged_in") is True


@app.route("/config/login", methods=["GET", "POST"])
def config_login():
    cfg = load_config()
    error = None
    if request.method == "POST":
        if request.form.get("password") == cfg.get("config_password"):
            session["logged_in"] = True
            return redirect(url_for("config_page"))
        error = "Bledne haslo."
    return render_template("login.html", error=error)


@app.route("/config/logout")
def config_logout():
    session.pop("logged_in", None)
    return redirect(url_for("dashboard"))


@app.route("/config", methods=["GET", "POST"])
def config_page():
    if not require_login():
        return redirect(url_for("config_login"))

    cfg = load_config()
    message = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_group":
            group_name = request.form.get("group_name", "").strip()
            if group_name:
                cfg.setdefault("groups", []).append({"id": str(uuid.uuid4()), "name": group_name})
                save_config(cfg)
                message = f"Dodano grupe: {group_name}."
            else:
                message = "Podaj nazwe grupy."

        elif action == "delete_group":
            gid = request.form.get("group_id")
            cfg["groups"] = [g for g in cfg.get("groups", []) if g["id"] != gid]
            for p in cfg.get("patients", []):
                if p.get("group_id") == gid:
                    p["group_id"] = ""
            save_config(cfg)
            message = "Usunieto grupe."

        elif action == "save_layout":
            cfg["columns"] = int(request.form.get("columns", cfg["columns"]))
            cfg["window_width"] = int(request.form.get("window_width", cfg["window_width"]))
            cfg["window_height"] = int(request.form.get("window_height", cfg["window_height"]))
            cfg["polling_interval_seconds"] = int(request.form.get("polling_interval_seconds", cfg["polling_interval_seconds"]))
            cfg["card_font_scale"] = max(40, min(200, int(request.form.get("card_font_scale", cfg["card_font_scale"]))))
            save_config(cfg)
            message = "Zapisano ustawienia wygladu."

        elif action == "change_password":
            new_pass = request.form.get("new_password", "").strip()
            if new_pass:
                cfg["config_password"] = new_pass
                save_config(cfg)
                message = "Zmieniono haslo."

        elif action == "save_alerts":
            try:
                t_low = int(request.form.get("threshold_low", cfg["threshold_low"]))
                t_high = int(request.form.get("threshold_high", cfg["threshold_high"]))
                repeat = int(request.form.get("alert_repeat_seconds", cfg["alert_repeat_seconds"]))
                if t_low >= t_high:
                    message = "Prog niskiego cukru musi byc mniejszy niz prog wysokiego."
                else:
                    cfg["threshold_low"] = t_low
                    cfg["threshold_high"] = t_high
                    cfg["alert_repeat_seconds"] = max(5, repeat)
                    save_config(cfg)
                    message = "Zapisano progi alarmowe."
            except ValueError:
                message = "Progi musza byc liczbami."

        elif action == "reset_sound":
            which = request.form.get("which")
            if which == "low":
                cfg["sound_low_file"] = "default_low.wav"
                save_config(cfg)
                message = "Przywrocono domyslny dzwiek (niski cukier)."
            elif which == "high":
                cfg["sound_high_file"] = "default_high.wav"
                save_config(cfg)
                message = "Przywrocono domyslny dzwiek (wysoki cukier)."

        elif action == "upload_sound":
            which = request.form.get("which")
            file = request.files.get("sound_file")
            if which not in ("low", "high") or not file or not file.filename:
                message = "Nie wybrano pliku dzwiekowego."
            else:
                ext = os.path.splitext(file.filename)[1].lower()
                if ext not in ALLOWED_SOUND_EXT:
                    message = "Dozwolone formaty dzwieku: .wav, .mp3, .ogg"
                else:
                    os.makedirs(SOUNDS_DIR, exist_ok=True)
                    fname = f"custom_{which}{ext}"
                    file.save(os.path.join(SOUNDS_DIR, fname))
                    cfg[f"sound_{which}_file"] = fname
                    save_config(cfg)
                    message = "Wgrano nowy dzwiek alarmu."

        elif action == "add_patient":
            name = request.form.get("name", "").strip()
            source = request.form.get("source", "dexcom").strip() or "dexcom"
            group_id = request.form.get("group_id", "").strip()
            
            if source == "carelink":
                carelink_file = request.form.get("carelink_token_file", "").strip()
                if name and carelink_file:
                    cfg["patients"].append({
                        "id": str(uuid.uuid4()), "name": name, "source": "carelink",
                        "carelink_token_file": carelink_file, "group_id": group_id
                    })
                    save_config(cfg)
                    message = f"Dodano: {name} (CareLink)."
                else:
                    message = "Uzupelnij imie i sciezke do pliku tokenu CareLink."
            elif source == "nightscout":
                ns_url = request.form.get("nightscout_url", "").strip()
                ns_token = request.form.get("nightscout_token", "").strip()
                if name and ns_url:
                    cfg["patients"].append({
                        "id": str(uuid.uuid4()), "name": name, "source": "nightscout",
                        "nightscout_url": ns_url, "nightscout_token": ns_token, "group_id": group_id,
                    })
                    save_config(cfg)
                    message = f"Dodano: {name} (Nightscout)."
                else:
                    message = "Uzupelnij imie i adres URL Nightscout."
            elif source == "librelinkup":
                llu_email = request.form.get("librelinkup_email", "").strip()
                llu_password = request.form.get("librelinkup_password", "").strip()
                llu_region = request.form.get("librelinkup_region", "eu").strip() or "eu"
                llu_patient_id = request.form.get("librelinkup_patient_id", "").strip()
                if name and llu_email and llu_password:
                    entry = {
                        "id": str(uuid.uuid4()), "name": name, "source": "librelinkup",
                        "librelinkup_email": llu_email, "librelinkup_password": llu_password,
                        "librelinkup_region": llu_region, "group_id": group_id,
                    }
                    if llu_patient_id:
                        entry["librelinkup_patient_id"] = llu_patient_id
                    cfg["patients"].append(entry)
                    save_config(cfg)
                    message = f"Dodano: {name} (LibreLinkUp)."
                else:
                    message = "Uzupelnij imie, e-mail i haslo LibreLinkUp."
            else:
                login = request.form.get("login", "").strip()
                password = request.form.get("password", "").strip()
                region = request.form.get("region", "ous").strip() or "ous"
                if name and login and password:
                    cfg["patients"].append({
                        "id": str(uuid.uuid4()), "name": name, "source": "dexcom",
                        "login": login, "password": password, "region": region, "group_id": group_id,
                    })
                    save_config(cfg)
                    message = f"Dodano: {name} (Dexcom)."
                else:
                    message = "Uzupelnij imie, login i haslo."

        elif action == "set_patient_group":
            pid = request.form.get("patient_id")
            gid = request.form.get("group_id", "").strip()
            for p in cfg.get("patients", []):
                if p["id"] == pid:
                    p["group_id"] = gid
            save_config(cfg)
            message = "Zmieniono grupe dziecka."

        elif action == "delete_patient":
            pid = request.form.get("patient_id")
            cfg["patients"] = [p for p in cfg["patients"] if p["id"] != pid]
            save_config(cfg)
            with readings_lock:
                readings_cache.pop(pid, None)
            message = "Usunieto pacjenta."

        elif action == "import_txt":
            file = request.files.get("txt_file")
            added = 0
            if file and file.filename:
                content = file.read().decode("utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    
                    # Format CareLink: carelink,<sciezka_do_pliku_tokenu>,<Imie>,<grupa(opcjonalnie)>
                    if parts[0].lower() == "carelink" and len(parts) >= 3:
                        _, token_file, name = parts[0], parts[1], parts[2]
                        group_name = parts[3] if len(parts) >= 4 else ""
                        if token_file and name:
                            cfg["patients"].append({
                                "id": str(uuid.uuid4()), "name": name, "source": "carelink",
                                "carelink_token_file": token_file,
                                "group_id": get_or_create_group_id(cfg, group_name),
                            })
                            added += 1
                        continue
                    # Format LibreLinkUp: librelinkup,<email>,<haslo>,<region>,<Imie>,<patient_id(opcjonalnie)>,<grupa(opcjonalnie)>
                    if parts[0].lower() == "librelinkup" and len(parts) >= 5:
                        _, llu_email, llu_password, llu_region, name = parts[0], parts[1], parts[2], parts[3], parts[4]
                        llu_patient_id = parts[5] if len(parts) >= 6 else ""
                        group_name = parts[6] if len(parts) >= 7 else ""
                        if llu_email and llu_password and name:
                            entry = {
                                "id": str(uuid.uuid4()), "name": name, "source": "librelinkup",
                                "librelinkup_email": llu_email, "librelinkup_password": llu_password,
                                "librelinkup_region": llu_region or "eu",
                                "group_id": get_or_create_group_id(cfg, group_name),
                            }
                            if llu_patient_id:
                                entry["librelinkup_patient_id"] = llu_patient_id
                            cfg["patients"].append(entry)
                            added += 1
                        continue
                    # Format Nightscout: nightscout,<url>,<token(moze byc puste)>,<Imie>,<grupa(opcjonalnie)>
                    if parts[0].lower() == "nightscout" and len(parts) >= 4:
                        _, ns_url, ns_token, name = parts[0], parts[1], parts[2], parts[3]
                        group_name = parts[4] if len(parts) >= 5 else ""
                        if ns_url and name:
                            cfg["patients"].append({
                                "id": str(uuid.uuid4()), "name": name, "source": "nightscout",
                                "nightscout_url": ns_url, "nightscout_token": ns_token,
                                "group_id": get_or_create_group_id(cfg, group_name),
                            })
                            added += 1
                        continue
                    # Format Dexcom (domyslny): login,haslo,Imie,region(opcjonalnie),grupa(opcjonalnie)
                    if len(parts) >= 3:
                        login, password, name = parts[0], parts[1], parts[2]
                        region = parts[3] if len(parts) >= 4 else "ous"
                        group_name = parts[4] if len(parts) >= 5 else ""
                        cfg["patients"].append({
                            "id": str(uuid.uuid4()), "name": name, "source": "dexcom",
                            "login": login, "password": password, "region": region,
                            "group_id": get_or_create_group_id(cfg, group_name),
                        })
                        added += 1
                save_config(cfg)
                message = f"Zaimportowano {added} pacjentow z pliku."
            else:
                message = "Nie wybrano pliku."

        cfg = load_config()

    return render_template("config.html", cfg=cfg, message=message)


if __name__ == "__main__":
    load_config()
    t = threading.Thread(target=polling_loop, daemon=True)
    t.start()
    print("=" * 60)
    print("Monitor cukru - uruchomiony z obsluga CareLink (Medtronic).")
    print("Panel glowny:      http://localhost:5000")
    print("Panel konfiguracji: http://localhost:5000/config")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
