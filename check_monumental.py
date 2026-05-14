#!/usr/bin/env python3
"""
Monumental Alert — corre en GitHub Actions cada 6 horas.

Usa Gemini (tier gratis de Google AI Studio) con grounding de Google Search
para detectar eventos confirmados en el Estadio Más Monumental (River Plate)
en los próximos 120 días. Compara contra el state guardado en el repo. Si
hay eventos nuevos, manda mail a Laura.
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).parent
STATE_PATH = ROOT / "state" / "events.json"
RECIPIENT = "laura.pirotta@gmail.com"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = """Sos un asistente que busca en la web eventos confirmados en el Estadio Más Monumental (estadio de River Plate, Núñez, Buenos Aires, Argentina).

Tu tarea: encontrar TODOS los eventos confirmados con fecha exacta que se vayan a hacer en el Monumental en los próximos 120 días.

Incluí:
- Recitales y conciertos (cualquier artista, nacional o internacional)
- Partidos de River como local: Copa Libertadores, Copa Sudamericana, Copa Argentina, Superclásico (River vs Boca), Selección Argentina
- Eventos masivos especiales (festivales, espectáculos)

NO incluyas:
- Partidos rutinarios del torneo local argentino (Liga Profesional) salvo Superclásico
- Eventos rumoreados sin confirmación oficial
- Eventos sin fecha definida

Fuentes confiables:
- riverplate.com.ar
- Ticketek Argentina (ticketek.com.ar)
- Sitios de noticias deportivas (TyC, Olé, Infobae)
- Pages oficiales de los artistas

Devolvé SOLO un bloque JSON válido, sin texto antes ni después, con este formato exacto:

{
  "eventos": [
    {
      "id": "slug-unico-en-kebab-case",
      "nombre": "Nombre del evento",
      "fecha": "YYYY-MM-DD",
      "tipo": "recital" | "libertadores" | "sudamericana" | "copa-argentina" | "superclasico" | "seleccion" | "otro",
      "fuente": "URL de la fuente más confiable"
    }
  ]
}

El "id" tiene que ser estable y único: combiná artista/equipo + fecha. Por ejemplo: "acdc-2026-03-23", "river-vs-boca-2026-05-04", "bad-bunny-2026-02-13".
Si un artista tiene varias fechas, usá un id distinto por fecha.
"""

USER_PROMPT = """Buscá en la web ahora mismo qué eventos confirmados hay en el Estadio Más Monumental (River Plate) entre hoy y los próximos 120 días.

Hacé varias búsquedas para cubrir bien: recitales, partidos internacionales de River, eventos especiales. Verificá fechas en al menos 2 fuentes cuando sea posible.

Devolveme el JSON pedido."""


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"eventos": [], "ultima_revision": None}


def save_state(state: dict) -> None:
    state["ultima_revision"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def fetch_events_from_gemini() -> list[dict]:
    api_key = os.environ["GEMINI_API_KEY"]
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": USER_PROMPT}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }
    resp = requests.post(
        GEMINI_URL,
        params={"key": api_key},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    raw = "".join(p.get("text", "") for p in parts).strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw_json = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise RuntimeError(f"No JSON found in Gemini response:\n{raw[:500]}")
        raw_json = raw[start : end + 1]

    parsed = json.loads(raw_json)
    eventos = parsed.get("eventos", [])

    today = datetime.now(timezone.utc).date().isoformat()
    cleaned = []
    seen_ids = set()
    for ev in eventos:
        eid = ev.get("id")
        fecha = ev.get("fecha")
        if not eid or not fecha or fecha < today:
            continue
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        cleaned.append(
            {
                "id": eid,
                "nombre": ev.get("nombre", "").strip(),
                "fecha": fecha,
                "tipo": ev.get("tipo", "otro"),
                "fuente": ev.get("fuente", ""),
            }
        )
    return cleaned


def diff_events(current: list[dict], previous: list[dict]) -> list[dict]:
    prev_ids = {e["id"] for e in previous}
    return [e for e in current if e["id"] not in prev_ids]


TIPO_LABEL = {
    "recital": "🎸 Recital",
    "libertadores": "🏆 Copa Libertadores",
    "sudamericana": "🏆 Copa Sudamericana",
    "copa-argentina": "🏆 Copa Argentina",
    "superclasico": "⚽ Superclásico",
    "seleccion": "🇦🇷 Selección Argentina",
    "otro": "📌 Evento especial",
}


def format_event_html(ev: dict) -> str:
    fecha_str = datetime.fromisoformat(ev["fecha"]).strftime("%d/%m/%Y")
    dia_semana = {
        0: "lunes",
        1: "martes",
        2: "miércoles",
        3: "jueves",
        4: "viernes",
        5: "sábado",
        6: "domingo",
    }[datetime.fromisoformat(ev["fecha"]).weekday()]
    tipo = TIPO_LABEL.get(ev["tipo"], "📌 Evento")
    dias_falta = (datetime.fromisoformat(ev["fecha"]).date() - datetime.now(timezone.utc).date()).days
    fuente = ev.get("fuente", "")
    fuente_html = f'<br><small><a href="{fuente}" style="color:#666">Fuente</a></small>' if fuente else ""
    return f"""
    <div style="border-left:4px solid #E30613;padding:14px 16px;margin:14px 0;background:#fff8f8;border-radius:4px">
      <div style="font-size:16px;font-weight:bold;color:#222">{ev['nombre']}</div>
      <div style="margin-top:6px;color:#444">
        📅 <strong>{dia_semana} {fecha_str}</strong> &nbsp;·&nbsp; faltan {dias_falta} días<br>
        {tipo}{fuente_html}
      </div>
    </div>
    """


def build_email(nuevos: list[dict]) -> tuple[str, str]:
    n = len(nuevos)
    plural = "evento nuevo" if n == 1 else f"{n} eventos nuevos"
    subject = f"🏟️ Monumental: {plural} confirmado{'s' if n > 1 else ''} — subí el Airbnb"

    cards = "\n".join(format_event_html(e) for e in sorted(nuevos, key=lambda x: x["fecha"]))
    html = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#222">
  <h2 style="color:#E30613;margin-bottom:4px">🏟️ Nuevos eventos en el Monumental</h2>
  <p style="color:#555;margin-top:0">
    Se confirmaron <strong>{plural}</strong> en el Estadio Más Monumental.
    Acordate de subir el precio del Airbnb desde 3-5 días antes hasta 1-2 días después de cada evento.
  </p>
  {cards}
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:12px">
    Este aviso lo genera un sistema automático que revisa cada 6 horas si hay eventos nuevos confirmados en el Monumental.
    Si querés cambiar algo, hablale a Nacho.
  </p>
</body></html>"""
    return subject, html


def send_email(subject: str, html_body: str) -> None:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["MAIL_OAUTH_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["MAIL_OAUTH_CLIENT_ID"],
        client_secret=os.environ["MAIL_OAUTH_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(Request())

    msg = MIMEMultipart("alternative")
    msg["To"] = RECIPIENT
    msg["From"] = "Monumental Alert"
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main() -> int:
    state = load_state()
    previous = state.get("eventos", [])

    print(f"[{datetime.now(timezone.utc).isoformat()}] Buscando eventos en el Monumental...")
    current = fetch_events_from_gemini()
    print(f"Eventos detectados: {len(current)}")
    for e in current:
        print(f"  - {e['fecha']}  {e['nombre']}  ({e['tipo']})")

    nuevos = diff_events(current, previous)
    print(f"Eventos nuevos vs state: {len(nuevos)}")

    if nuevos:
        subject, html_body = build_email(nuevos)
        send_email(subject, html_body)
        print(f"✉️  Mail enviado a {RECIPIENT}: {subject}")

    merged_ids = {e["id"] for e in previous}
    merged = list(previous)
    today = datetime.now(timezone.utc).date().isoformat()
    merged = [e for e in merged if e["fecha"] >= today]
    for e in current:
        if e["id"] not in {x["id"] for x in merged}:
            merged.append({**e, "notificado_en": today})
    merged.sort(key=lambda x: x["fecha"])

    state["eventos"] = merged
    save_state(state)
    print(f"State actualizado: {len(merged)} eventos vigentes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
