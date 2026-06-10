"""
╔══════════════════════════════════════════════════════════╗
║     CODIGO DE ORO — Bot XAU/USD v3.0 para Railway       ║
║  Filosofia: pocas alertas, todas de calidad             ║
║  Solo avisa cuando hay contexto claro de entrada        ║
╚══════════════════════════════════════════════════════════╝
"""
import os
import time
import requests
from collections import deque
from datetime import datetime

# ══════════════════════════════════════════════════════════
# CONFIGURACION
# ══════════════════════════════════════════════════════════
TOKEN     = os.environ.get("TELEGRAM_TOKEN", "8804236118:AAEsOWK0sk8ZAcUTXAD8ZYWiMm5OGPn07Xs")
CHAT_IDS  = [c.strip() for c in os.environ.get("CHAT_ID", "1842727203").split(",") if c.strip()]
TD_KEYS   = [k.strip() for k in os.environ.get("TWELVEDATA_KEYS", "").split(",") if k.strip()]
INTERVALO = 15      # segundos entre ticks (XAU — TwelveData tiene limite de creditos)
HIST_MAX  = 360     # 360 x 15s = 90 minutos de historial

# Cooldowns — tiempo minimo entre alertas del mismo tipo
CD = {
    "entrada_compra":  1800,   # 30 min entre señales de compra
    "entrada_venta":   1800,   # 30 min entre señales de venta
    "retroceso_baj":    900,   # 15 min entre alertas de retroceso bajista
    "soporte_roto":     600,   # 10 min
    "rebote_soporte":   600,
    "resumen":         3600,   # resumen cada 1 hora (solo informativo)
}

# ══════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════
historial = deque(maxlen=HIST_MAX)
key_idx   = 0
cooldowns = {}
soporte   = float(os.environ.get("SOPORTE", "0"))

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

def en_cooldown(id_cd):
    ahora  = time.time()
    cd_seg = CD.get(id_cd, 600)
    if id_cd in cooldowns and ahora - cooldowns[id_cd] < cd_seg:
        return True
    cooldowns[id_cd] = ahora
    return False

def peek_cooldown(id_cd):
    """Consulta si esta en cooldown SIN activarlo."""
    ahora  = time.time()
    cd_seg = CD.get(id_cd, 600)
    return id_cd in cooldowns and ahora - cooldowns[id_cd] < cd_seg

def telegram(msg):
    for cid in CHAT_IDS:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )
            if r.status_code == 200:
                log(f"TG OK -> {cid}: {msg[:50].strip()}")
            else:
                log(f"TG error {r.status_code} -> {cid}")
        except Exception as e:
            log(f"TG excepcion -> {cid}: {e}")

# ══════════════════════════════════════════════════════════
# FETCH PRECIO XAU — TwelveData
# ══════════════════════════════════════════════════════════
def get_precio():
    key = sig_key()
    if not key:
        log("Sin TWELVEDATA_KEYS — modo simulacion")
        if historial:
            import random
            return round(historial[-1]["precio"] + random.uniform(-0.3, 0.3), 2)
        return None
    try:
        r = requests.get(
            f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={key}",
            timeout=10
        )
        data = r.json()
        if "price" in data:
            return float(data["price"])
        log(f"TwelveData respuesta inesperada: {data}")
        return None
    except Exception as e:
        log(f"Fetch error: {e}")
        return None

def registrar(precio):
    if not precio or precio < 1500 or precio > 9000:
        return False
    if historial:
        ultimo     = historial[-1]["precio"]
        cambio_pct = abs(precio - ultimo) / ultimo * 100
        if cambio_pct > 2.0:
            log(f"Anomalia XAU: {ultimo} -> {precio} ({cambio_pct:.1f}%) — IGNORADO")
            historial.append({"precio": precio, "ts": time.time(), "anomalo": True})
            return False
    historial.append({"precio": precio, "ts": time.time(), "anomalo": False})
    return True

# ══════════════════════════════════════════════════════════
# INDICADORES
# ══════════════════════════════════════════════════════════
def precios_validos():
    return [r["precio"] for r in historial if not r.get("anomalo")]

def ema(precios, periodo):
    if len(precios) < periodo:
        return None
    k   = 2 / (periodo + 1)
    val = sum(precios[:periodo]) / periodo
    for p in precios[periodo:]:
        val = p * k + val * (1 - k)
    return round(val, 2)

def rsi(precios, periodo=14):
    if len(precios) < periodo + 1:
        return None
    g      = precios[-(periodo + 1):]
    deltas = [g[i] - g[i-1] for i in range(1, len(g))]
    avg_g  = sum(x for x in deltas if x > 0) / periodo
    avg_p  = sum(abs(x) for x in deltas if x < 0) / periodo
    if avg_p == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_p)), 1)

def get_velocidad(minutos):
    validos = [(r["precio"], r["ts"]) for r in historial if not r.get("anomalo")]
    if len(validos) < 2:
        return None
    ahora  = time.time()
    target = ahora - minutos * 60
    mejor  = min(validos, key=lambda r: abs(r[1] - target))
    margen = minutos * 60 * (2.0 if minutos >= 30 else 1.5)
    if abs(mejor[1] - target) > margen:
        return None
    return round(validos[-1][0] - mejor[0], 2)

# ══════════════════════════════════════════════════════════
# LOGICA CENTRAL — misma filosofia que BTC v2.0
#
# Para COMPRA se requiere TODO esto junto:
#   1. ORO lleva bajando (v30 negativo >= 5 pts) — "viene de abajo"
#   2. En los ultimos 5 min ya empezo a subir (v5 positivo >= 3 pts)
#   3. EMA9 cruzando o encima de EMA21
#   4. RSI no esta en sobrecompra (< 70)
#   5. Score total >= 70
#
# Para VENTA se requiere TODO esto junto:
#   1. ORO lleva subiendo (v30 positivo >= 5 pts) — "viene de arriba"
#   2. En los ultimos 5 min ya empezo a caer (v5 negativo <= -3 pts)
#   3. EMA9 cruzando o debajo de EMA21
#   4. RSI no esta en sobreventa (> 30)
#   5. Score total >= 70
# ══════════════════════════════════════════════════════════
def analizar(precio, v5, v15, v30, e9, e21, e20, e50, rsi_v):
    """
    Retorna: ("compra"|"venta"|"esperar", score, razones, sl, tp, rr)
    Solo retorna compra/venta cuando el contexto completo esta alineado.
    """
    if e9 is None or e21 is None or e20 is None or e50 is None:
        return "esperar", 0, [], 0, 0, 0
    if v5 is None or v30 is None:
        return "esperar", 0, [], 0, 0, 0

    razones_c = []
    razones_v = []
    score_c   = 0
    score_v   = 0

    # ── CONTEXTO 30 MIN: lleva bajando o subiendo ──
    # Filtro principal: solo buscamos compra si el ORO viene bajando
    # (posible suelo) y solo venta si viene subiendo (posible techo)
    if v30 < -5:
        score_c += 30
        razones_c.append(f"Lleva bajando {v30:+.1f} pts en 30m — posible suelo")
    elif v30 > 5:
        score_v += 30
        razones_v.append(f"Lleva subiendo {v30:+.1f} pts en 30m — posible techo")
    else:
        # Sin tendencia clara en 30m — no hay contexto de entrada
        return "esperar", 0, [], 0, 0, 0

    # ── CAMBIO DE DIRECCION en 5 min ──
    # Para compra: v30 negativo pero v5 ya positivo (giro al alza)
    # Para venta:  v30 positivo pero v5 ya negativo (giro a la baja)
    if v5 > 3:
        score_c += 25
        razones_c.append(f"Giro alcista en 5m: +{v5:.1f} pts")
    elif v5 < -2:  # CAMBIO v3: mas sensible para detectar giros bajistas
        score_v += 25
        razones_v.append(f"Giro bajista en 5m: {v5:.1f} pts")
    else:
        # Sin giro confirmado todavia
        return "esperar", 0, [], 0, 0, 0

    # ── CONFIRMACION 15 MIN ──
    # Si v15 confirma la misma direccion que v5, suma puntos
    if v15 is not None:
        if v5 > 0 and v15 > 0:
            score_c += 10
            razones_c.append(f"15m confirma alza: +{v15:.1f} pts ✅")
        elif v5 < 0 and v15 < 0:
            score_v += 10
            razones_v.append(f"15m confirma caida: {v15:.1f} pts ✅")

    # ── EMA9 vs EMA21 ──
    diff_ema = e9 - e21
    if diff_ema > 0:
        score_c += 20
        razones_c.append(f"EMA9 sobre EMA21 (+{diff_ema:.2f}) ✅")
    elif diff_ema > -3:
        # Muy cerca del cruce — posible cambio inminente
        score_c += 10
        razones_c.append(f"EMA9 acercandose a EMA21 ({diff_ema:.2f}) — cruce proximo")
    else:
        score_v += 20
        razones_v.append(f"EMA9 bajo EMA21 ({diff_ema:.2f}) ✅")

    # ── TENDENCIA ESTRUCTURAL EMA20 vs EMA50 ──
    if e20 > e50:
        score_c += 15
        razones_c.append("EMA20 > EMA50 — estructura alcista ✅")
    else:
        score_v += 15
        razones_v.append("EMA20 < EMA50 — estructura bajista ✅")

    # ── RSI ──
    if rsi_v is not None:
        if rsi_v < 35:
            score_c += 20
            razones_c.append(f"RSI {rsi_v} — zona sobreventa, rebote probable ✅")
        elif rsi_v < 55:
            score_c += 10
            razones_c.append(f"RSI {rsi_v} — zona neutra/alcista ✅")
        elif rsi_v > 65:
            score_v += 20
            razones_v.append(f"RSI {rsi_v} — zona sobrecompra, caida probable ✅")
        elif rsi_v > 45:
            score_v += 10
            razones_v.append(f"RSI {rsi_v} — zona neutra/bajista ✅")

    # ── DECISION FINAL ──
    # Contexto coherente: compra = v30 baja + v5 sube / venta = v30 sube + v5 baja
    coherente_compra = v30 < 0 and v5 > 0
    coherente_venta  = v30 > 0 and v5 < 0

    if coherente_compra and score_c >= 70 and (rsi_v is None or rsi_v < 70):
        # SL/TP para XAU: basado en volatilidad reciente
        sl_base = max(5.0, round(abs(v5) * 2.0, 1))
        rr      = 2.0 if score_c >= 80 else 1.5
        entrada = round(precio + 0.30, 2)
        sl      = round(entrada - sl_base, 2)
        tp      = round(entrada + sl_base * rr, 2)
        return "compra", score_c, razones_c, sl, tp, rr

    if coherente_venta and score_v >= 70 and (rsi_v is None or rsi_v > 30):
        sl_base = max(5.0, round(abs(v5) * 2.0, 1))
        rr      = 2.0 if score_v >= 80 else 1.5
        entrada = round(precio - 0.30, 2)
        sl      = round(entrada + sl_base, 2)
        tp      = round(entrada - sl_base * rr, 2)
        return "venta", score_v, razones_v, sl, tp, rr

    return "esperar", max(score_c, score_v), [], 0, 0, 0

# ══════════════════════════════════════════════════════════
# MENSAJES
# ══════════════════════════════════════════════════════════
def msg_entrada(dir, precio, score, razones, sl, tp, rr, v5, v15, v30, rsi_v):
    sl_pts  = round(abs(precio - sl), 2)
    tp_pts  = round(abs(tp - precio), 2)
    # XM: 1 Troy Ounce = $1 por punto en ORO
    sl_usd  = round(sl_pts * 1.0, 2)
    tp_usd  = round(tp_pts * 1.0, 2)
    emoji   = "🟢" if dir == "compra" else "🔴"
    titulo  = "ENTRADA COMPRA" if dir == "compra" else "ENTRADA VENTA"
    calidad = "🔥 Muy alta" if score >= 85 else "✅ Alta" if score >= 75 else "👍 Buena"
    v5_txt  = f"+{v5:.1f}" if v5 >= 0 else f"{v5:.1f}"
    v15_txt = f"+{v15:.1f}" if v15 >= 0 else f"{v15:.1f}"
    v30_txt = f"+{v30:.1f}" if v30 >= 0 else f"{v30:.1f}"
    return (
        f"{emoji} <b>{titulo} — XAU/USD (ORO)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio actual: <b>{precio:.2f}</b>\n"
        f"📊 RSI: {rsi_v or 'N/D'}  |  Score: {score}/100\n"
        f"⏱ 5m: {v5_txt} pts  |  15m: {v15_txt} pts  |  30m: {v30_txt} pts\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Entrada sugerida: <b>{precio + (0.30 if dir=='compra' else -0.30):.2f}</b>\n"
        f"🎯 Take Profit: <b>{tp:.2f}</b>  (+{tp_pts:.1f} pts  ≈ <b>+${tp_usd:.2f} USD</b>)\n"
        f"🛑 Stop Loss:   <b>{sl:.2f}</b>  (-{sl_pts:.1f} pts  ≈ <b>-${sl_usd:.2f} USD</b>)\n"
        f"⚖️ Ratio R:R  1:{rr}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(f"  • {r}" for r in razones[:4]) + "\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📶 Calidad: <b>{calidad}</b>\n"
        f"⏰ {hora_txt()} — Revisar vela actual antes de entrar"
    )

def msg_retroceso_bajista(precio, v5, v15, v30, rsi_v):
    """Alerta intermedia: no es venta confirmada, es aviso de correccion."""
    return (
        f"🔶 <b>POSIBLE RETROCESO — XAU/USD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: <b>{precio:.2f}</b>\n"
        f"⏱ 5m: {v5:+.1f} pts  |  15m: {v15:+.1f} pts  |  30m: {v30:+.1f} pts\n"
        f"📊 RSI: {rsi_v or 'N/D'}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ No es señal de venta confirmada\n"
        f"  • Si tienes compra abierta: proteger ganancias\n"
        f"  • Si buscas entrada: esperar mejor precio\n"
        f"  • Posible correccion bajista en curso\n"
        f"⏰ {hora_txt()}"
    )

def msg_soporte_roto(precio, sop, v5):
    return (
        f"🚨 <b>SOPORTE ROTO — XAU/USD</b>\n"
        f"Soporte: <b>{sop:.2f}</b>\n"
        f"Precio actual: <b>{precio:.2f}</b>\n"
        f"Caida desde soporte: {abs(precio - sop):.2f} pts\n"
        f"⚠️ Esperar rebote confirmado antes de comprar\n"
        f"⏰ {hora_txt()}"
    )

def msg_rebote_soporte(precio, sop, v5, rsi_v):
    return (
        f"🟡 <b>REBOTE EN SOPORTE — XAU/USD</b>\n"
        f"Soporte: <b>{sop:.2f}</b>\n"
        f"Precio: <b>{precio:.2f}</b>  (+{v5:.1f} pts en 5m)\n"
        f"RSI: {rsi_v or 'N/D'}\n"
        f"👀 Posible entrada compra — esperar confirmacion\n"
        f"⏰ {hora_txt()}"
    )

def msg_resumen(precio, dir, score, v5, v15, v30, rsi_v, hist_len):
    estado  = "🟢 Alcista" if dir == "compra" else "🔴 Bajista" if dir == "venta" else "⏳ Sin señal"
    v5_txt  = f"{v5:+.1f} pts" if v5 is not None else "N/D"
    v15_txt = f"{v15:+.1f} pts" if v15 is not None else "N/D"
    v30_txt = f"{v30:+.1f} pts" if v30 is not None else "N/D"
    return (
        f"📋 <b>Resumen XAU/USD — {hora_txt()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: <b>{precio:.2f}</b>\n"
        f"📊 RSI: {rsi_v or 'N/D'}  |  Score: {score}/100\n"
        f"⏱ 5m: {v5_txt}  |  15m: {v15_txt}  |  30m: {v30_txt}\n"
        f"📡 Datos: {hist_len}/{HIST_MAX}\n"
        f"Estado: <b>{estado}</b>"
    )

# ══════════════════════════════════════════════════════════
# EVALUACION
# ══════════════════════════════════════════════════════════
def evaluar(precio):
    ps    = precios_validos()
    v5    = get_velocidad(5)
    v15   = get_velocidad(15)
    v30   = get_velocidad(30)
    e9    = ema(ps, 9)
    e21   = ema(ps, 21)
    e20   = ema(ps, 20)
    e50   = ema(ps, 50)
    rsi_v = rsi(ps, 14)

    v5_txt  = f"{v5:+.1f}" if v5 is not None else "N/D"
    v30_txt = f"{v30:+.1f}" if v30 is not None else "N/D"
    log(f"XAU={precio:.2f}  v5={v5_txt}  v30={v30_txt}  RSI={rsi_v}  hist={len(ps)}")

    # CAMBIO v3: minimo 60 ticks (15 min) para que v30 tenga datos suficientes
    if len(ps) < 60:
        log(f"Acumulando datos: {len(ps)}/60")
        return

    # ── 1. Soporte roto ──
    if soporte > 0 and precio < soporte - 0.5:
        if not en_cooldown("soporte_roto"):
            telegram(msg_soporte_roto(precio, soporte, v5 or 0))
        return

    # ── 2. Rebote desde soporte (aviso previo, no señal completa) ──
    if soporte > 0 and precio >= soporte and precio <= soporte + 2.0:
        if v5 is not None and v5 > 2:
            if not en_cooldown("rebote_soporte"):
                telegram(msg_rebote_soporte(precio, soporte, v5, rsi_v))

    # ── 3. Señal de entrada principal ──
    dir, score, razones, sl, tp, rr = analizar(
        precio, v5, v15, v30, e9, e21, e20, e50, rsi_v
    )
    log(f"Analisis: {dir} | score={score}")

    if dir == "compra" and not peek_cooldown("entrada_compra"):
        en_cooldown("entrada_compra")
        telegram(msg_entrada("compra", precio, score, razones, sl, tp, rr,
                              v5 or 0, v15 or 0, v30 or 0, rsi_v))
        return

    if dir == "venta" and not peek_cooldown("entrada_venta"):
        en_cooldown("entrada_venta")
        telegram(msg_entrada("venta", precio, score, razones, sl, tp, rr,
                              v5 or 0, v15 or 0, v30 or 0, rsi_v))
        return

    # ── 4. Alerta de retroceso bajista (advertencia, no señal de venta) ──
    # Se activa cuando: v30 positivo (venia subiendo) + v5 negativo (empezo a caer)
    # pero la señal de venta completa aun no se cumplio
    # Util para: proteger compras abiertas o esperar mejor entrada
    if (v30 is not None and v30 > 5 and
        v5 is not None and v5 < -2 and
        dir != "venta"):   # solo si no ya salio señal de venta
        if not peek_cooldown("retroceso_baj"):
            en_cooldown("retroceso_baj")
            telegram(msg_retroceso_bajista(
                precio, v5, v15 or 0, v30, rsi_v
            ))

    # ── 5. Resumen horario (solo informativo) ──
    if not peek_cooldown("resumen"):
        en_cooldown("resumen")
        telegram(msg_resumen(precio, dir, score,
                              v5, v15, v30, rsi_v, len(ps)))

# ══════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════
def main():
    log("═══ Codigo de Oro XAU Bot v3.0 arrancando ═══")
    telegram(
        "✅ <b>Bot XAU/USD (ORO) v3.0 activo</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🔍 Monitoreando XAU/USD 24/7\n"
        "📊 Analisis: EMA 9/21/20/50 + RSI + Impulso 5m/15m/30m\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Logica de señal:</b>\n"
        "  • Solo avisa cuando hay contexto real\n"
        "  • COMPRA: lleva bajando + giro al alza confirmado\n"
        "  • VENTA: lleva subiendo + giro a la baja confirmado\n"
        "  • Cooldown 30 min entre señales del mismo tipo\n"
        "  • 🔶 Alerta retroceso bajista (aviso, no venta)\n"
        "  • Resumen informativo cada 1 hora\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Intervalo: cada {INTERVALO}s  |  Buffer: {HIST_MAX} ticks (90 min)"
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
            log("Bot detenido.")
            break
        except Exception as e:
            log(f"Error inesperado: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
