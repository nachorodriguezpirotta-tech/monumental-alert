# Monumental Alert

Sistema automático que vigila eventos confirmados en el **Estadio Más Monumental** (River Plate) y le manda un mail a `laura.pirotta@gmail.com` apenas detecta uno nuevo. Pensado para subir el precio del Airbnb a tiempo.

Corre en **GitHub Actions** cada 6 horas, sin depender de ninguna computadora.

## Cómo funciona

1. Workflow `.github/workflows/check.yml` se dispara por cron (cada 6 horas).
2. `check_monumental.py` llama a la API de Anthropic con `web_search` para buscar eventos confirmados en los próximos 120 días.
3. Compara la lista contra `state/events.json` (que vive en el repo).
4. Si encontró eventos que **no estaban** en el state, manda un mail HTML por SMTP de Gmail a Laura con los nuevos.
5. Commitea el state actualizado al repo (así los próximos runs ya no repiten avisos).

Eventos que incluye: recitales, Libertadores, Sudamericana, Copa Argentina, Superclásico, Selección. Ignora los partidos rutinarios de Liga Profesional.

## Setup inicial (una sola vez)

### 1. Subir el repo a GitHub

Desde esta carpeta:

```bash
cd ~/Documents/Claude/monumental-alert
git init
git add .
git commit -m "initial commit"
gh repo create monumental-alert --private --source=. --push
```

(Si no tenés `gh` CLI, podés crear el repo a mano en github.com y hacer `git remote add origin ...` + `git push -u origin main`.)

### 2. Configurar los 3 secrets en GitHub

Andá al repo en GitHub → Settings → Secrets and variables → Actions → New repository secret. Creá estos tres:

| Secret | Valor |
| --- | --- |
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic (console.anthropic.com → API Keys) |
| `GMAIL_USER` | `nacho.rodriguezpirotta@gmail.com` |
| `GMAIL_APP_PASSWORD` | Un App Password de 16 caracteres de Gmail (ver abajo) |

### 3. Generar el Gmail App Password

Gmail no acepta tu contraseña normal por SMTP. Necesitás un App Password:

1. Andá a https://myaccount.google.com/security
2. Tiene que estar activado **2-Step Verification** (si no, activalo primero).
3. Después en https://myaccount.google.com/apppasswords creá un app password con el nombre "monumental-alert".
4. Copiá los 16 caracteres (sin espacios) y pegalos en el secret `GMAIL_APP_PASSWORD`.

### 4. Disparar la primera corrida

En GitHub → pestaña **Actions** → workflow "Check Monumental Events" → botón **Run workflow**.

Mirá los logs. Si todo OK, vas a ver los eventos detectados y, la primera vez, Laura va a recibir el mail con TODOS los eventos vigentes (porque el state está vacío).

A partir de ahí, solo va a recibir mails cuando aparezca alguno nuevo.

## Mantenimiento

- **Cambiar el destinatario**: editar `RECIPIENT` arriba en `check_monumental.py`.
- **Cambiar la frecuencia**: editar el `cron` en `.github/workflows/check.yml`. `"15 */6 * * *"` = cada 6 horas. Más frecuente: `"15 */3 * * *"` (cada 3h).
- **Ver el historial de eventos detectados**: `state/events.json` en el repo. Cada run lo commitea.
- **Re-disparar a mano**: pestaña Actions → Run workflow.
- **Borrar un evento "falso positivo"** de la memoria para forzar re-aviso: editá `state/events.json` quitando ese evento y commiteá.

## Costo

- GitHub Actions: gratis para repos privados con < 2.000 min/mes. Cada run son ~30 segundos, 4 runs/día = ~2 min/día = 60 min/mes. Sobra.
- Anthropic API (web_search): ~$0.01–0.05 por run. Aprox. $1–5/mes.
- Gmail SMTP: gratis.
