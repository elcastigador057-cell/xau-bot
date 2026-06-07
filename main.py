"""
╔══════════════════════════════════════════════════════════╗
║       CODIGO DE ORO — Bot XAU/USD v2.0 para Railway     ║
║  Analisis completo: EMA, RSI, impulso, señal operativa  ║
║  Mensajes inteligentes con entrada, TP y SL calculados  ║
╚══════════════════════════════════════════════════════════╝
"""
import os
import time
import math
import requests
from collections import deque
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════
# CONFIGURACION — variables de entorno en Railway
# ══════════════════════════════════════════════════════════
TOKEN        = os.environ.get("TELEGRAM_TOKEN", "8804236118:AAEsOWK0sk8ZAcUTXAD8ZYWiMm5OGPn07Xs")
CHAT_ID      = os.environ.get("CHAT_ID",        "1842727203")
TD_KEYS      = [k.strip() for k in os.environ.get("TWELVEDATA_KEYS", "").split(",") if k.strip()]
SOPORTE_ENV  = float(os.environ.get("SOPORTE", "0"))   # soporte fijo, 0 = desactivado
INTERVALO    = 15        # segundos entre ticks
HIST_MAX     = 180       # 180 registros = 15 min a 15s/tick

# Umbrales de señal para XAU
UMBRAL_V5_FUERTE  = 20   # pts en 5 min para señal fuerte
UMBRAL_V5_MEDIA   = 10   # pts en 5 min para señal media

# Cooldowns — cuanto tiempo esperar antes de repetir cada tipo de alerta
CD = {
    "oportunidad_compra": 600,   # 10 min — la señal mas importante
    "oportunidad_venta":  600,
    "impulso_fuerte":     300,   # 5 min
    "impulso_medio":      480,   # 8 min
    "soporte_roto":       300,
    "rebote_soporte":     300,
    "resumen":           1800,   # resumen cada 30 min
}

# ══════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════
historial   = deque(maxlen=HIST_MAX)  # {precio, ts, anomalo}
key_idx     = 0
cooldowns   = {}
soporte     = SOPORTE_ENV
ultima_sig  = None   # ultima señal enviada para evitar repetir
alertas_seguidas_baj = 0   # contador alertas bajistas consecutivas
alertas_seguidas_alc = 0

# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def hora_txt():
    return datetime.now().strftime("%H:%M")

def sig_key():
    global key_idx
    if not TD_KEYS:
        return None
    k = TD_KEYS[key_idx % len(TD_KEYS)]
    key_idx += 1
    return k

def en_cooldown(id_cd, seg=None):
    """True si la alerta esta en cooldown. Si no, marca y retorna False."""
    ahora = time.time()
    cd_seg = seg or CD.get(id_cd, 300)
    if id_cd in cooldowns and ahora - cooldowns[id_cd] < cd_seg:
        return True
    cooldowns[id_cd] = ahora
    return False

def telegram(msg):
    """Envia mensaje a Telegram."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        if r.status_code == 200:
            log(f"TG enviado: {msg[:50].strip()}")
        else:
            log(f"TG error {r.status_code}: {r.text[:80]}")
    except Exception as e:
        log(f"TG excepcion: {e}")

# ══════════════════════════════════════════════════════════
# FETCH PRECIO XAU
# ══════════════════════════════════════════════════════════
def get_precio():
    key = sig_key()
    if not key:
        log("Sin TWELVEDATA_KEYS — usando simulacion")
        # Simulacion si no hay key (para testing)
        if historial:
            import random
            return round(historial[-1]["precio"] + random.uniform(-0.5, 0.5), 2)
        return None
    try:
        url = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={key}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if "price" in data:
            return float(data["price"])
        log(f"TwelveData respuesta: {data}")
        return None
    except Exception as e:
        log(f"Fetch error: {e}")
        return None

def registrar(precio):
    """Valida y registra precio en historial. Retorna True si es valido."""
    if not precio or precio < 1500 or precio > 9000:
        log(f"Precio fuera de rango: {precio}")
        return False
    if historial:
        ultimo = historial[-1]["precio"]
        cambio_pct = abs(precio - ultimo) / ultimo * 100
        if cambio_pct > 2.0:
            log(f"Anomalia detectada: {ultimo} -> {precio} ({cambio_pct:.1f}%) — IGNORADO")
            historial.append({"precio": precio, "ts": time.time(), "anomalo": True})
            return False
    historial.append({"precio": precio, "ts": time.time(), "anomalo": False})
    return True

# ══════════════════════════════════════════════════════════
# INDICADORES TECNICOS
# ══════════════════════════════════════════════════════════
def precios_validos():
    """Retorna lista de precios sin anomalias."""
    return [r["precio"] for r in historial if not r.get("anomalo")]

def ema(precios, periodo):
    """Calcula EMA de una lista de precios."""
    if len(precios) < periodo:
        return None
    k = 2 / (periodo + 1)
    ema_val = sum(precios[:periodo]) / periodo
    for p in precios[periodo:]:
        ema_val = p * k + ema_val * (1 - k)
    return round(ema_val, 2)

def rsi(precios, periodo=14):
    """Calcula RSI."""
    if len(precios) < periodo + 1:
        return None
    deltas = [precios[i] - precios[i-1] for i in range(1, len(precios))]
    ganancias = [d for d in deltas if d > 0]
    perdidas  = [abs(d) for d in deltas if d < 0]
    if not ganancias:
        return 0.0
    if not perdidas:
        return 100.0
    # Usar solo los ultimos N periodos
    g = deltas[-periodo:]
    avg_g = sum(x for x in g if x > 0) / periodo
    avg_p = sum(abs(x) for x in g if x < 0) / periodo
    if avg_p == 0:
        return 100.0
    rs = avg_g / avg_p
    return round(100 - (100 / (1 + rs)), 1)

def get_velocidad(minutos):
    """Cambio de precio en los ultimos N minutos. Solo precios validos."""
    validos = [(r["precio"], r["ts"]) for r in historial if not r.get("anomalo")]
    if len(validos) < 2:
        return None
    ahora = time.time()
    target = ahora - minutos * 60
    mejor = min(validos, key=lambda r: abs(r[1] - target), default=None)
    if not mejor or abs(mejor[1] - target) > minutos * 60 * 1.5:
        return None
    return round(validos[-1][0] - mejor[0], 2)

def calcular_spread():
    """Estima volatilidad reciente (rango medio de los ultimos 12 registros = 1 min)."""
    validos = precios_validos()[-12:]
    if len(validos) < 3:
        return 1.0
    return round(max(validos) - min(validos), 2)

# ══════════════════════════════════════════════════════════
# CALCULO DE SEÑAL OPERATIVA
# ══════════════════════════════════════════════════════════
def calcular_senal(precio, v1, v5, v15, ema9, ema21, ema20, ema50, rsi_val):
    """
    Retorna dict con:
      - direccion: 'compra' | 'venta' | 'esperar'
      - confianza: 0-100
      - entrada, sl, tp calculados
      - razon: texto explicativo
      - it: indice de tendencia 0-100
    """
    score = 50  # neutral
    razones = []

    # ── EMA 9 vs 21 (peso alto — tendencia rapida) ──
    if ema9 and ema21:
        if ema9 > ema21:
            score += 18
            razones.append("EMA9 sobre EMA21 ✅")
        else:
            score -= 18
            razones.append("EMA9 bajo EMA21 ❌")

    # ── EMA 20 vs 50 (peso medio — tendencia larga) ──
    if ema20 and ema50:
        if ema20 > ema50:
            score += 12
            razones.append("Tendencia alcista ✅")
        else:
            score -= 12
            razones.append("Tendencia bajista ❌")

    # ── RSI ──
    if rsi_val is not None:
        if rsi_val < 30:
            score += 15
            razones.append(f"RSI {rsi_val} — sobreventa ✅")
        elif rsi_val > 70:
            score -= 15
            razones.append(f"RSI {rsi_val} — sobrecompra ❌")
        elif 45 < rsi_val < 65:
            score += 8
            razones.append(f"RSI {rsi_val} — zona saludable ✅")
        else:
            razones.append(f"RSI {rsi_val} — neutral")

    # ── Impulso 5 min ──
    if v5 is not None:
        if v5 > 15:
            score += 12
            razones.append(f"Impulso alcista +{v5} pts ✅")
        elif v5 < -15:
            score -= 12
            razones.append(f"Impulso bajista {v5} pts ❌")
        elif abs(v5) < 5:
            razones.append("Precio lateral")

    # ── Confirmacion 15 min ──
    if v15 is not None:
        if v15 > 0 and v5 is not None and v5 > 0:
            score += 8
            razones.append("Tendencia 15m confirma ✅")
        elif v15 < 0 and v5 is not None and v5 < 0:
            score -= 8

    score = max(0, min(100, score))

    # ── Determinar direccion ──
    if score >= 68:
        direccion = "compra"
        confianza = score
    elif score <= 32:
        direccion = "venta"
        confianza = 100 - score
    else:
        direccion = "esperar"
        confianza = 50

    # ── Calcular entrada, SL, TP ──
    spread = calcular_spread()
    sl_base = max(8, round(spread * 1.5, 1))
    rr      = 2.0 if confianza >= 75 else 1.5

    if direccion == "compra":
        entrada = round(precio + 0.30, 2)   # spread de entrada
        sl      = round(entrada - sl_base, 2)
        tp      = round(entrada + sl_base * rr, 2)
    elif direccion == "venta":
        entrada = round(precio - 0.30, 2)
        sl      = round(entrada + sl_base, 2)
        tp      = round(entrada - sl_base * rr, 2)
    else:
        entrada = sl = tp = 0

    return {
        "direccion": direccion,
        "confianza": confianza,
        "it": score,
        "entrada": entrada,
        "sl": sl,
        "tp": tp,
        "sl_pts": sl_base,
        "tp_pts": round(sl_base * rr, 1),
        "rr": rr,
        "razones": razones,
        "v1": v1, "v5": v5, "v15": v15,
        "rsi": rsi_val,
        "ema9": ema9, "ema21": ema21,
    }

# ══════════════════════════════════════════════════════════
# GENERADOR DE MENSAJES
# ══════════════════════════════════════════════════════════
def msg_oportunidad_compra(precio, s):
    v5  = f"+{s['v5']:.1f}" if s['v5'] else "N/D"
    v15 = f"+{s['v15']:.1f}" if s['v15'] and s['v15'] > 0 else (f"{s['v15']:.1f}" if s['v15'] else "N/D")
    confianza_txt = "Alta" if s['confianza'] >= 80 else "Media-Alta" if s['confianza'] >= 68 else "Media"
    return (
        f"🟢 <b>OPORTUNIDAD DE COMPRA — XAU/USD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio actual: <b>{precio:.2f}</b>\n"
        f"📈 Impulso: {v5} pts en 5 min | {v15} pts en 15 min\n"
        f"📊 RSI: {s['rsi'] or 'N/D'} | IT: {s['it']}/100\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <b>Entrada sugerida:</b> {s['entrada']:.2f}\n"
        f"🎯 <b>Take Profit:</b> {s['tp']:.2f} (+{s['tp_pts']} pts)\n"
        f"🛑 <b>Stop Loss:</b> {s['sl']:.2f} (-{s['sl_pts']} pts)\n"
        f"⚖️ Relacion R:R 1:{s['rr']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Señales:\n" +
        "\n".join(f"  {r}" for r in s['razones'][:4]) + "\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📶 Confianza: <b>{confianza_txt} ({s['confianza']}%)</b>\n"
        f"⏰ {hora_txt()} — Confirmar con siguiente vela antes de entrar"
    )

def msg_oportunidad_venta(precio, s):
    v5  = f"{s['v5']:.1f}" if s['v5'] else "N/D"
    v15 = f"{s['v15']:.1f}" if s['v15'] else "N/D"
    confianza_txt = "Alta" if s['confianza'] >= 80 else "Media-Alta" if s['confianza'] >= 68 else "Media"
    return (
        f"🔴 <b>OPORTUNIDAD DE VENTA — XAU/USD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio actual: <b>{precio:.2f}</b>\n"
        f"📉 Impulso: {v5} pts en 5 min | {v15} pts en 15 min\n"
        f"📊 RSI: {s['rsi'] or 'N/D'} | IT: {s['it']}/100\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <b>Entrada sugerida:</b> {s['entrada']:.2f}\n"
        f"🎯 <b>Take Profit:</b> {s['tp']:.2f} (-{s['tp_pts']} pts)\n"
        f"🛑 <b>Stop Loss:</b> {s['sl']:.2f} (+{s['sl_pts']} pts)\n"
        f"⚖️ Relacion R:R 1:{s['rr']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Señales:\n" +
        "\n".join(f"  {r}" for r in s['razones'][:4]) + "\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📶 Confianza: <b>{confianza_txt} ({s['confianza']}%)</b>\n"
        f"⏰ {hora_txt()} — Confirmar con siguiente vela antes de entrar"
    )

def msg_impulso_fuerte(precio, v5, v15, direccion):
    emoji = "📈" if direccion == "alc" else "📉"
    return (
        f"{emoji} <b>Impulso fuerte XAU/USD</b>\n"
        f"Precio: <b>{precio:.2f}</b>\n"
        f"5 min: <b>{v5:+.1f} pts</b> | 15 min: {v15:+.1f} pts\n"
        f"⏰ {hora_txt()} — Revisar app para señal completa"
    )

def msg_soporte_roto(precio, sop, v5):
    return (
        f"🚨 <b>SOPORTE ROTO — XAU/USD</b>\n"
        f"Soporte: <b>{sop:.2f}</b> → Precio: <b>{precio:.2f}</b>\n"
        f"Caida desde soporte: {abs(precio - sop):.2f} pts\n"
        f"Impulso 5m: {v5:+.1f} pts\n"
        f"⚠️ No comprar hasta confirmar rebote\n"
        f"⏰ {hora_txt()}"
    )

def msg_rebote_soporte(precio, sop, rsi_val):
    return (
        f"🟢 <b>REBOTE en soporte — XAU/USD</b>\n"
        f"Soporte: <b>{sop:.2f}</b> — Precio: <b>{precio:.2f}</b>\n"
        f"RSI: {rsi_val or 'N/D'} — {'Sobreventa, rebote probable ✅' if rsi_val and rsi_val < 35 else 'Vigilar confirmacion'}\n"
        f"💡 Posible entrada en compra si confirma\n"
        f"⏰ {hora_txt()}"
    )

def msg_resumen(precio, s, hist_len):
    it_txt = (
        "🔴 Venta fuerte" if s['it'] < 30 else
        "🟠 Presion bajista" if s['it'] < 45 else
        "🟡 Indeciso" if s['it'] < 60 else
        "🟢 Compra probable" if s['it'] < 80 else
        "🚀 Compra fuerte"
    )
    v5_txt  = f"{s['v5']:+.1f} pts" if s['v5'] is not None else "N/D"
    v15_txt = f"{s['v15']:+.1f} pts" if s['v15'] is not None else "N/D"
    return (
        f"📋 <b>Resumen XAU/USD — {hora_txt()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: <b>{precio:.2f}</b>\n"
        f"📊 IT: {s['it']}/100 — {it_txt}\n"
        f"⚡ Impulso 5m: {v5_txt} | 15m: {v15_txt}\n"
        f"📈 RSI: {s['rsi'] or 'N/D'}\n"
        f"🗂 Historial: {hist_len}/180 registros\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Estado: <b>{'🟢 COMPRA' if s['direccion']=='compra' else '🔴 VENTA' if s['direccion']=='venta' else '⏳ ESPERAR'}</b>"
    )

# ══════════════════════════════════════════════════════════
# LOGICA PRINCIPAL DE EVALUACION
# ══════════════════════════════════════════════════════════
def evaluar(precio):
    global ultima_sig, alertas_seguidas_baj, alertas_seguidas_alc

    # ── Calcular indicadores ──────────────────────────────
    ps    = precios_validos()
    v1    = get_velocidad(1)
    v5    = get_velocidad(5)
    v15   = get_velocidad(15)
    e9    = ema(ps, 9)
    e21   = ema(ps, 21)
    e20   = ema(ps, 20)
    e50   = ema(ps, 50)
    rsi_v = rsi(ps, 14)

    log(f"XAU={precio:.2f}  v5={v5:+.1f if v5 else 'N/D'}  RSI={rsi_v}  EMA9={e9}  IT calculando...")

    # CAMBIO: Esperar historial completo (180) antes de evaluar
    # Asi evitamos alertas falsas al arrancar por datos incompletos
    if len(ps) < 180:
        log(f"Acumulando historial: {len(ps)}/180 — sin alertas hasta completar")
        return

    s = calcular_senal(precio, v1, v5, v15, e9, e21, e20, e50, rsi_v)
    log(f"Señal: {s['direccion']} | IT={s['it']} | Confianza={s['confianza']}%")

    # ── 1. Soporte roto ──────────────────────────────────
    if soporte > 0 and precio < soporte - 0.5:
        if not en_cooldown("soporte_roto"):
            telegram(msg_soporte_roto(precio, soporte, v5 or 0))
        alertas_seguidas_baj += 1
        alertas_seguidas_alc = 0
        return

    # ── 2. Rebote en soporte ─────────────────────────────
    if soporte > 0 and soporte <= precio <= soporte + 2.0:
        if s['it'] >= 55 and not en_cooldown("rebote_soporte"):
            telegram(msg_rebote_soporte(precio, soporte, rsi_v))
        return

    # ── 3. Señal de COMPRA de alta confianza ────────────
    if s['direccion'] == "compra" and s['confianza'] >= 68:
        if not en_cooldown("oportunidad_compra"):
            telegram(msg_oportunidad_compra(precio, s))
            ultima_sig = "compra"
            alertas_seguidas_alc += 1
            alertas_seguidas_baj = 0
        return

    # ── 4. Señal de VENTA de alta confianza ─────────────
    if s['direccion'] == "venta" and s['confianza'] >= 68:
        if not en_cooldown("oportunidad_venta"):
            telegram(msg_oportunidad_venta(precio, s))
            ultima_sig = "venta"
            alertas_seguidas_baj += 1
            alertas_seguidas_alc = 0
        return

    # ── 5. Impulso fuerte sin señal completa ─────────────
    # Solo avisar si el impulso es fuerte pero los indicadores no alinean aun
    if v5 is not None and abs(v5) >= UMBRAL_V5_FUERTE:
        dir_imp = "alc" if v5 > 0 else "baj"
        if not en_cooldown(f"impulso_{dir_imp}"):
            telegram(msg_impulso_fuerte(precio, v5, v15 or 0, dir_imp))
        return

    # ── 6. Resumen periodico (cada 30 min) ───────────────
    if not en_cooldown("resumen"):
        telegram(msg_resumen(precio, s, len(ps)))

# ══════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════
def main():
    log("═══ Codigo de Oro Bot v2.0 arrancando ═══")

    if not TD_KEYS:
        log("ADVERTENCIA: No hay TWELVEDATA_KEYS — usando modo simulacion")

    telegram(
        "✅ <b>Codigo de Oro Bot v2.0 activo</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🔍 Monitoreando XAU/USD 24/7\n"
        "📊 Analisis: EMA 9/21/20/50, RSI, Impulso\n"
        "📲 Solo recibiras alertas cuando hay oportunidad real\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Intervalo: cada {INTERVALO} segundos\n"
        f"🗂 Buffer: 180 registros (15 min)\n"
        f"🛡 Filtro anomalias: >2% entre ticks = ignorado"
    )

    while True:
        try:
            precio = get_precio()
            if precio:
                valido = registrar(precio)
                if valido:
                    evaluar(precio)
            time.sleep(INTERVALO)
        except KeyboardInterrupt:
            log("Bot detenido manualmente.")
            break
        except Exception as e:
            log(f"Error inesperado: {e}")
            time.sleep(30)   # esperar 30s antes de reintentar

if __name__ == "__main__":
    main()
