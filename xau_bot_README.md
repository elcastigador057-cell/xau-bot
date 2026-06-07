# Codigo de Oro — Bot XAU/USD v2.0

Monitorea el oro 24/7 y envía alertas inteligentes a Telegram
con señal operativa completa: entrada, TP, SL y análisis.

## Mensajes que recibiras

### 🟢 Oportunidad de COMPRA (alta confianza)
```
🟢 OPORTUNIDAD DE COMPRA — XAU/USD
💰 Precio actual: 4462.50
📈 Impulso: +18.3 pts en 5 min | +32.1 pts en 15 min
📊 RSI: 38 | IT: 72/100
💡 Entrada sugerida: 4462.80
🎯 Take Profit: 4481.80 (+19 pts)
🛑 Stop Loss: 4450.30 (-12.5 pts)
⚖️ Relacion R:R 1:1.5
Confianza: Media-Alta (72%)
⏰ 14:32 — Confirmar con siguiente vela
```

### 📋 Resumen (cada 30 min)
Solo muestra estado actual — sin spam.

### 🚨 Soporte roto
Solo cuando el precio rompe el nivel que configuraste.

## Cuándo NO te manda mensajes
- Cuando el mercado está lateral (IT 40-60)
- Menos de 30 registros acumulados (primeros 7 min)
- Cuando acabas de recibir la misma alerta (cooldown)

## Variables de entorno en Railway

| Variable | Valor |
|---|---|
| TELEGRAM_TOKEN | 8804236118:AAEsOWK0sk8ZAcUTXAD8ZYWiMm5OGPn07Xs |
| CHAT_ID | 1842727203 |
| TWELVEDATA_KEYS | key1,key2,key3,key4,key5 |
| SOPORTE | 4450.00 (opcional, 0 = desactivado) |

## Despliegue en Railway

1. Sube estos archivos a GitHub (repo `xau-bot`)
2. Railway → New Project → Deploy from GitHub
3. Agrega las variables de entorno
4. El bot arranca solo

## Costo estimado
Menos de $0.50/mes en Railway (plan gratuito cubre de sobra).
