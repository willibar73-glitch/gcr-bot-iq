"""
SUPERBOT GCR ELITE — BOT 2 (IQ OPTION) v1.0
Misma lógica de análisis que el Bot 1 (GCR+APEXBOT+SUPERBOT+DELTABOT fusion),
pero usando velas REALES de la cuenta demo de IQ Option en vez de Twelve Data.

Cuenta: PRACTICE (demo) forzada por código — nunca opera con dinero real.
Firebase: base de datos SEPARADA (gcr-bot-iq), no toca el bot 1.

Variables de entorno necesarias en Railway:
  IQ_EMAIL    -> correo de IQ Option
  IQ_PASSWORD -> contraseña de IQ Option
"""
import os, sys, time, math
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import requests
import pytz

from iqoptionapi.stable_api import IQ_Option

# ══ CONFIG ══
FIREBASE_URL = "https://gcr-bot-iq-default-rtdb.firebaseio.com"
# 4 pares principales (lunes a viernes, mercado real)
PARES_NORMAL = ["EURUSD", "EURJPY", "EURGBP", "GBPUSD"]
# Mismos 4 pares en versión OTC (sábado y domingo, mercado sintético de IQ Option)
PARES_OTC = ["EURUSD-OTC", "EURJPY-OTC", "EURGBP-OTC", "GBPUSD-OTC"]

def es_fin_de_semana():
    # weekday(): 0=lunes ... 5=sábado, 6=domingo
    return datetime.now(TZ_CO).weekday() >= 5

def pares_actuales():
    return PARES_OTC if es_fin_de_semana() else PARES_NORMAL
TZ_CO = pytz.timezone("America/Bogota")
DELAY_PARES = 2

TENDENCIA_MULT = 4
SLOPE_MIN = 0.0015
MIN_ESPACIADO = 2
MIN_CRUZADO = 1

EMAIL = os.environ.get("IQ_EMAIL")
PASSWORD = os.environ.get("IQ_PASSWORD")

if not EMAIL or not PASSWORD:
    print("❌ FALTAN credenciales IQ_EMAIL / IQ_PASSWORD en Variables de Railway")
    sys.exit(1)


def _safe(d):
    if isinstance(d, dict):
        return {k: _safe(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_safe(v) for v in d]
    if isinstance(d, float):
        if math.isnan(d) or math.isinf(d):
            return 0
        return d
    return d


def get_params():
    h = datetime.now(TZ_CO).hour
    if 20 <= h < 22:
        return {"RSI_CALL": 30, "RSI_PUT": 70, "RSI_CALL_A": 40, "RSI_PUT_A": 60,
                "DAMOA": 2.5, "VELAS_MIN": 1, "SCORE_MIN": 1, "VOL_FACTOR": 0.15,
                "STOCH_OS": 30, "STOCH_OB": 70}
    if 9 <= h < 14:
        return {"RSI_CALL": 35, "RSI_PUT": 65, "RSI_CALL_A": 42, "RSI_PUT_A": 58,
                "DAMOA": 2.0, "VELAS_MIN": 1, "SCORE_MIN": 1, "VOL_FACTOR": 0.15,
                "STOCH_OS": 30, "STOCH_OB": 70}
    return {"RSI_CALL": 28, "RSI_PUT": 72, "RSI_CALL_A": 36, "RSI_PUT_A": 64,
            "DAMOA": 2.4, "VELAS_MIN": 1, "SCORE_MIN": 2, "VOL_FACTOR": 0.2,
            "STOCH_OS": 25, "STOCH_OB": 75}


def sesion_activa():
    h = datetime.now(TZ_CO).hour + datetime.now(TZ_CO).minute / 60
    if 9.0 <= h < 11.0: return "Londres"
    if 11.0 <= h < 14.0: return "NY"
    if 20.0 <= h < 22.0: return "Nocturna"
    if 0.0 <= h < 9.0: return "Madrugada"
    return "Tarde"


Iq = None

def conectar():
    global Iq
    Iq = IQ_Option(EMAIL, PASSWORD)
    ok, razon = Iq.connect()
    if not ok:
        print(f" ❌ No se pudo conectar a IQ Option: {razon}")
        return False
    try:
        Iq.change_balance("PRACTICE")
    except Exception as e:
        print(f" ⚠️ No se pudo confirmar modo PRACTICE: {e}")
    print(" ✅ Conectado a IQ Option (cuenta DEMO)")
    return True


def asegurar_conexion():
    global Iq
    try:
        if Iq is None or not Iq.check_connect():
            print(" 🔄 Reconectando a IQ Option...")
            return conectar()
        return True
    except Exception:
        return conectar()


def obtener_datos(symbol_iq):
    if not asegurar_conexion():
        return None
    try:
        velas = Iq.get_candles(symbol_iq, 60, 100, time.time())
        if not velas or len(velas) < 60:
            return None
        df = pd.DataFrame(velas)
        df = df.rename(columns={"max": "high", "min": "low"})
        df = df.sort_values("from").reset_index(drop=True)
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c].astype(float)
        return df[["open", "high", "low", "close"]]
    except Exception as e:
        print(f" ❌ {symbol_iq}: {e}")
        return None


def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()

def rsi_tma(close, n=14, half=5, dev_p=100, devs=2.0):
    d = close.diff()
    avgU = d.where(d > 0, 0.0).rolling(n).mean()
    avgD = (-d.where(d < 0, 0.0)).rolling(n).mean()
    r = 100 - (100 / (1 + avgU / avgD.replace(0, np.nan)))
    r = r.fillna(50)
    hl = int(half / 2) + 1
    tma = sma(sma(r, hl), hl)
    dev = devs * (r - tma).abs().rolling(dev_p).mean()
    cmo = avgU - avgD
    return r, tma + dev, tma - dev, cmo

def bollinger(close, n=20, dev=2.0):
    m = sma(close, n); s = close.rolling(n).std()
    return m + dev * s, m, m - dev * s

def damoa(high, low, close, nivel=4.0):
    base = ((high + low) / 2).rolling(3).mean()
    vol = (high - low).abs().rolling(5).mean() * 0.2
    norm = (close - base) / vol.replace(0, 1)
    return norm, norm <= -nivel, norm >= nivel

def stoch(high, low, close, k=13):
    hh = high.rolling(k).max(); ll = low.rolling(k).min()
    return ((close - ll) / (hh - ll).replace(0, 1)) * 100

def macd(close, f=12, s=26, sig=9):
    ml = ema(close, f) - ema(close, s)
    ms = ema(ml, sig)
    return ml, ms

def velas_bb(high, low, bs, bi):
    ca = cb = 0
    for i in range(len(high) - 2, max(len(high) - 10, -1), -1):
        if high.iloc[i] > bs.iloc[i]: ca += 1
        else: break
    for i in range(len(low) - 2, max(len(low) - 10, -1), -1):
        if low.iloc[i] < bi.iloc[i]: cb += 1
        else: break
    return ca, cb

def calidad_vela(o, h, l, c, idx=-2):
    rng = float(h.iloc[idx] - l.iloc[idx])
    if rng == 0: return False, False, False, False, False
    cue = abs(float(c.iloc[idx]) - float(o.iloc[idx]))
    cmin = min(float(o.iloc[idx]), float(c.iloc[idx]))
    cmax = max(float(o.iloc[idx]), float(c.iloc[idx]))
    mi = cmin - float(l.iloc[idx])
    ms_ = float(h.iloc[idx]) - cmax
    t = rng / 3
    doji = cue >= rng * 0.28
    cup = float(c.iloc[idx]) >= float(l.iloc[idx]) + t * 2
    cdn = float(c.iloc[idx]) <= float(h.iloc[idx]) - t * 2
    mbuy = mi >= rng * 0.2
    msell = ms_ >= rng * 0.2
    return doji, cup, cdn, mbuy, msell

def ema_contexto(close, idx=-2):
    eR = ema(close, 3); eM = ema(close, 9); eL = ema(close, 21); eC = ema(close, 50)
    gap_abs = (eR - eM).abs()
    gap_min = gap_abs.rolling(50).mean() * 0.1
    gap_ok_bull = ((eR - eM) > gap_min) & ((eM - eL) > gap_min)
    gap_ok_bear = ((eM - eR) > gap_min) & ((eL - eM) > gap_min)
    bull = (float(eR.iloc[idx]) > float(eM.iloc[idx]) and float(eM.iloc[idx]) > float(eL.iloc[idx]) and
            float(close.iloc[idx]) > float(eL.iloc[idx]) and bool(gap_ok_bull.iloc[idx]))
    bear = (float(eR.iloc[idx]) < float(eM.iloc[idx]) and float(eM.iloc[idx]) < float(eL.iloc[idx]) and
            float(close.iloc[idx]) < float(eL.iloc[idx]) and bool(gap_ok_bear.iloc[idx]))
    ctx_b = float(close.iloc[idx]) > float(eC.iloc[idx])
    ctx_s = float(close.iloc[idx]) < float(eC.iloc[idx])
    crz_b = float(eR.iloc[idx]) > float(eM.iloc[idx]) and float(eR.iloc[idx - 1]) <= float(eM.iloc[idx - 1])
    crz_s = float(eR.iloc[idx]) < float(eM.iloc[idx]) and float(eR.iloc[idx - 1]) >= float(eM.iloc[idx - 1])
    denom = max(abs(float(eM.iloc[idx - 3])), 1e-8)
    sl_m = (float(eM.iloc[idx]) - float(eM.iloc[idx - 3])) / denom * 100
    lat = not bull and not bear
    return bull, bear, ctx_b, ctx_s, crz_b, crz_s, sl_m, lat

def space_factor(high, low, close, idx=-2, lb=20, factor=0.3):
    at = float(ema(high - low, 10).iloc[idx])
    rs = float(high.rolling(lb).max().iloc[idx]); sp = float(low.rolling(lb).min().iloc[idx])
    c2 = float(close.iloc[idx])
    return (rs - c2) > at * factor, (c2 - sp) > at * factor

def sr_zona(high, low, close, idx=-2):
    at = float(ema(high - low, 10).iloc[idx])
    rs = float(high.rolling(20).max().iloc[idx]); sp = float(low.rolling(20).min().iloc[idx])
    c2 = float(close.iloc[idx])
    return abs(c2 - sp) <= at * 1.5, abs(rs - c2) <= at * 1.5

def no_agotado(close, open_, dir_, idx=-2):
    if dir_ == "CALL":
        return not all(float(close.iloc[idx - i]) > float(open_.iloc[idx - i]) for i in range(1, 7) if abs(idx - i) <= len(close))
    return not all(float(close.iloc[idx - i]) < float(open_.iloc[idx - i]) for i in range(1, 7) if abs(idx - i) <= len(close))

def en_tendencia_check(high, low, idx=-2, lb=50, mult=TENDENCIA_MULT):
    rango_50 = float(high.rolling(lb).max().iloc[idx]) - float(low.rolling(lb).min().iloc[idx])
    vela_prom = float(sma(high - low, lb).iloc[idx])
    if vela_prom == 0: return False
    return rango_50 > vela_prom * mult

def lejos_niveles(high, low, close, idx=-2, lb=20, factor=0.4):
    resist_nivel = float(high.rolling(lb).max().iloc[idx]); soport_nivel = float(low.rolling(lb).min().iloc[idx])
    rango_sma = float(sma(high - low, lb).iloc[idx]); c2 = float(close.iloc[idx])
    if rango_sma == 0: return False, False
    return (resist_nivel - c2) > rango_sma * factor, (c2 - soport_nivel) > rango_sma * factor

def momentum_velas(close, open_, idx=-2):
    bull_sum = bear_sum = 0.0
    for k in range(0, 5):
        j = idx - k
        if abs(j) > len(close): continue
        o_ = float(open_.iloc[j]); c_ = float(close.iloc[j])
        cuerpo = abs(c_ - o_)
        if c_ > o_: bull_sum += cuerpo
        else: bear_sum += cuerpo
    fuerza_alc = bull_sum > bear_sum; fuerza_baj = bear_sum > bull_sum
    fuerza_prev_up = (float(close.iloc[idx - 1]) > float(open_.iloc[idx - 1]) and float(close.iloc[idx - 2]) > float(open_.iloc[idx - 2]))
    fuerza_prev_dn = (float(close.iloc[idx - 1]) < float(open_.iloc[idx - 1]) and float(close.iloc[idx - 2]) < float(open_.iloc[idx - 2]))
    return fuerza_alc, fuerza_baj, fuerza_prev_up, fuerza_prev_dn

def clasificar_ruptura(o, h, l, c, idx=-2, umbral=0.5):
    rng = float(h.iloc[idx] - l.iloc[idx])
    if rng == 0: return False, True
    cuerpo = abs(float(c.iloc[idx]) - float(o.iloc[idx]))
    ratio = cuerpo / rng
    return ratio >= umbral, ratio < umbral

def score_total(rsi_v, cmo_v, ml_v, ms_v, ml_p, ms_p, sk, bs2, bi2, h2, l2, dir_, lejR=False, lejS=False):
    sb = ss = 0
    if l2 <= bi2: sb += 1
    if h2 >= bs2: ss += 1
    if sk <= 25: sb += 1
    if sk >= 75: ss += 1
    if rsi_v <= 40: sb += 1
    if rsi_v >= 60: ss += 1
    if ml_v > ms_v and ml_p <= ms_p: sb += 2
    elif ml_v > ms_v: sb += 1
    if ml_v < ms_v and ml_p >= ms_p: ss += 2
    elif ml_v < ms_v: ss += 1
    if cmo_v > 0: sb += 1
    if cmo_v < 0: ss += 1
    if lejR: sb += 1
    if lejS: ss += 1
    return sb if dir_ == "CALL" else ss


def analizar(symbol_mostrado, df):
    if df is None or len(df) < 60: return None
    try:
        p = get_params()
        c = df["close"]; h = df["high"]; l = df["low"]; o = df["open"]
        i = -2

        rsi_s, rup, rlo, cmo_s = rsi_tma(c)
        bs, bm, bi = bollinger(c)
        dm, dc, dv = damoa(h, l, c, p["DAMOA"])
        ca, cb = velas_bb(h, l, bs, bi)
        sk_s = stoch(h, l, c)
        ml_s, ms_s = macd(c)

        rsi_v = float(rsi_s.iloc[i]); rsi_v = 50.0 if math.isnan(rsi_v) else rsi_v
        dam_v = float(dm.iloc[i]); dam_v = 0.0 if math.isnan(dam_v) else dam_v
        d_c = bool(dc.iloc[i]) if not pd.isna(dc.iloc[i]) else False
        d_v = bool(dv.iloc[i]) if not pd.isna(dv.iloc[i]) else False
        sk2 = float(sk_s.iloc[i]); sk2 = 50.0 if math.isnan(sk2) else sk2
        ml2 = float(ml_s.iloc[i]); ml3 = float(ml_s.iloc[i - 1])
        ms2 = float(ms_s.iloc[i]); ms3 = float(ms_s.iloc[i - 1])
        cmo2 = float(cmo_s.iloc[i]); cmo2 = 0.0 if math.isnan(cmo2) else cmo2
        bs2 = float(bs.iloc[i]); bi2 = float(bi.iloc[i])
        h2 = float(h.iloc[i]); l2 = float(l.iloc[i])
        c2 = float(c.iloc[i]); o2 = float(o.iloc[i])
        c2_up = c2 > o2; c2_dn = c2 < o2

        rsi_bull = ((rsi_v > float(rlo.iloc[i]) and float(rsi_s.iloc[i - 1]) <= float(rlo.iloc[i - 1])) or
                    (rsi_v > 50 and float(rsi_s.iloc[i - 1]) <= 50))
        rsi_bear = ((rsi_v < float(rup.iloc[i]) and float(rsi_s.iloc[i - 1]) >= float(rup.iloc[i - 1])) or
                    (rsi_v < 50 and float(rsi_s.iloc[i - 1]) >= 50))

        emB, emBr, ctxB, ctxS, crzB, crzS, slM, lat = ema_contexto(c, i)
        doji, cup, cdn, mbuy, msell = calidad_vela(o, h, l, c, i)
        spU, spD = space_factor(h, l, c, i)
        enS, enR = sr_zona(h, l, c, i)
        no_ag = no_agotado(c, o, "CALL", i)
        no_ag_s = no_agotado(c, o, "PUT", i)
        vol_ok = float((h - l).iloc[i]) > float(sma(h - l, 20).iloc[i]) * p["VOL_FACTOR"]

        en_tend = en_tendencia_check(h, l, i)
        pendiente_ok = abs(slM) > SLOPE_MIN
        lejR, lejS = lejos_niveles(h, l, c, i)
        fuerza_alc, fuerza_baj, fuerza_prev_up, fuerza_prev_dn = momentum_velas(c, o, i)
        es_fuerte, es_debil = clasificar_ruptura(o, h, l, c, i)

        score_b = score_total(rsi_v, cmo2, ml2, ms2, ml3, ms3, sk2, bs2, bi2, h2, l2, "CALL", lejR, lejS)
        score_s = score_total(rsi_v, cmo2, ml2, ms2, ml3, ms3, sk2, bs2, bi2, h2, l2, "PUT", lejR, lejS)

        gcr_call = rsi_v <= p["RSI_CALL"] and d_c and cb >= p["VELAS_MIN"]
        gcr_put = rsi_v >= p["RSI_PUT"] and d_v and ca >= p["VELAS_MIN"]

        mT_buy = (emB and ctxB and rsi_bull and cmo2 > 0 and ml2 > ms2 and c2_up and doji and cup and
                  vol_ok and no_ag and en_tend and lejR and pendiente_ok and score_b >= p["SCORE_MIN"])
        mT_sell = (emBr and ctxS and rsi_bear and cmo2 < 0 and ml2 < ms2 and c2_dn and doji and cdn and
                   vol_ok and no_ag_s and en_tend and lejS and pendiente_ok and score_s >= p["SCORE_MIN"])

        mE_buy = (enS and mbuy and c2_up and doji and cup and (ctxB or lat) and vol_ok and not enR and score_b >= p["SCORE_MIN"])
        mE_sell = (enR and msell and c2_dn and doji and cdn and (ctxS or lat) and vol_ok and not enS and score_s >= p["SCORE_MIN"])

        mC_buy = (crzB and (ctxB or lat) and c2_up and doji and cup and vol_ok and en_tend and no_ag and rsi_bull and lejR and score_b >= p["SCORE_MIN"])
        mC_sell = (crzS and (ctxS or lat) and c2_dn and doji and cdn and vol_ok and en_tend and no_ag_s and rsi_bear and lejS and score_s >= p["SCORE_MIN"])

        mP_pullback_buy = (es_fuerte and enS and c2_up and doji and cup and mbuy and fuerza_alc and vol_ok and ctxB and en_tend and not enR)
        mP_pullback_sell = (es_fuerte and enR and c2_dn and doji and cdn and msell and fuerza_baj and vol_ok and ctxS and en_tend and not enS)
        mP_continuidad_buy = (es_debil and fuerza_prev_up and c2_up and doji and cup and vol_ok and ctxB and en_tend and rsi_bull and cmo2 > 0)
        mP_continuidad_sell = (es_debil and fuerza_prev_dn and c2_dn and doji and cdn and vol_ok and ctxS and en_tend and rsi_bear and cmo2 < 0)
        mP_reversion_buy = (enS and mbuy and c2_up and doji and cup and vol_ok and ctxB and en_tend and fuerza_alc and not enR)
        mP_reversion_sell = (enR and msell and c2_dn and doji and cdn and vol_ok and ctxS and en_tend and fuerza_baj and not enS)
        mP_buy = mP_pullback_buy or mP_continuidad_buy or mP_reversion_buy
        mP_sell = mP_pullback_sell or mP_continuidad_sell or mP_reversion_sell

        alerta_call = (not gcr_call) and ((rsi_v <= p["RSI_CALL_A"] and (d_c or cb >= 1)) or (d_c and cb >= 1) or (rsi_v <= p["RSI_CALL_A"] and cb >= 1))
        alerta_put = (not gcr_put) and ((rsi_v >= p["RSI_PUT_A"] and (d_v or ca >= 1)) or (d_v and ca >= 1) or (rsi_v >= p["RSI_PUT_A"] and ca >= 1))

        hay_call = (gcr_call or mT_buy or mE_buy or mC_buy or mP_buy) and not emBr
        hay_put = (gcr_put or mT_sell or mE_sell or mC_sell or mP_sell) and not emB
        hay_alerta_call = alerta_call and not emBr
        hay_alerta_put = alerta_put and not emB

        if not any([hay_call, hay_put, hay_alerta_call, hay_alerta_put]):
            return None

        if hay_call: direccion, tipo = "CALL", ("CONFIRMADA" if gcr_call else "ALERTA")
        elif hay_put: direccion, tipo = "PUT", ("CONFIRMADA" if gcr_put else "ALERTA")
        elif hay_alerta_call: direccion, tipo = "CALL", "ALERTA"
        else: direccion, tipo = "PUT", "ALERTA"

        if direccion == "CALL":
            if gcr_call: modo = "GCR"
            elif mT_buy: modo = "T"
            elif mE_buy: modo = "E"
            elif mC_buy: modo = "C"
            elif mP_buy: modo = "PCR"
            else: modo = "RSI"
            score = score_b
        else:
            if gcr_put: modo = "GCR"
            elif mT_sell: modo = "T"
            elif mE_sell: modo = "E"
            elif mC_sell: modo = "C"
            elif mP_sell: modo = "PCR"
            else: modo = "RSI"
            score = score_s

        fuerza = sum([
            gcr_call or gcr_put,
            emB if direccion == "CALL" else emBr,
            rsi_bull if direccion == "CALL" else rsi_bear,
            score >= 3,
            doji and (cup if direccion == "CALL" else cdn)
        ])
        if fuerza < 3:
            return None

        precio_v = float(c.iloc[-1])
        if math.isnan(precio_v): precio_v = c2

        return {
            "par": symbol_mostrado, "direccion": direccion, "tipo": tipo, "modo": modo,
            "precio": round(precio_v, 5),
            "rsi": round(rsi_v, 2), "damoa": round(dam_v, 2),
            "stoch": round(sk2, 1), "score": score,
            "velas_fuera": cb if direccion == "CALL" else ca,
            "fuerza": f"{fuerza}/5", "sesion": sesion_activa(),
            "fuente": "IQ Option (demo)",
            "confirmaciones": {
                "RSI GCR": "SI" if (gcr_call or gcr_put) else "NO",
                "DAMOA": "SI" if (d_c or d_v) else "NO",
                "Velas BB": "SI" if (cb >= 1 or ca >= 1) else "NO",
                "RSI TMA": "SI" if (rsi_bull if direccion == "CALL" else rsi_bear) else "NO",
                "EMA": "SI" if (emB if direccion == "CALL" else emBr) else "NO",
                "Vela calidad": "SI" if (doji and (cup if direccion == "CALL" else cdn)) else "NO",
                "Stoch": "SI" if (sk2 <= p["STOCH_OS"] if direccion == "CALL" else sk2 >= p["STOCH_OB"]) else "NO",
                "MACD": "SI" if (ml2 > ms2 if direccion == "CALL" else ml2 < ms2) else "NO",
                "SR zona": "SI" if (enS if direccion == "CALL" else enR) else "NO",
                "SpaceFactor": "SI" if (spU if direccion == "CALL" else spD) else "NO",
            },
            "hora": datetime.now(TZ_CO).strftime("%H:%M:%S"),
            "fecha": datetime.now(TZ_CO).strftime("%Y-%m-%d")
        }
    except Exception as e:
        print(f" ❌ Error {symbol_mostrado}: {e}")
        return None


def calcular_entrada():
    ahora = datetime.now(TZ_CO)
    siguiente = ahora.replace(second=0, microsecond=0) + timedelta(minutes=1)
    margen = (siguiente - ahora).total_seconds()
    if margen < 8:
        siguiente += timedelta(minutes=1)
    return siguiente.strftime("%H:%M:%S")


def publicar(s):
    try:
        s = dict(s)
        s["entrada"] = calcular_entrada()
        s_safe = _safe(s)
        r1 = requests.put(f"{FIREBASE_URL}/senalActiva.json", json=s_safe, timeout=5)
        print(f" ✅ Firebase OK — activa:{r1.status_code} — Entrada:{s['entrada']}")
        if r1.status_code >= 400:
            print(f"    ⚠️ Respuesta: {r1.text[:200]}")
    except Exception as e:
        print(f" ❌ Firebase: {e}")


def limpiar(msg="Analizando 8 pares (IQ Option demo)..."):
    try:
        requests.put(f"{FIREBASE_URL}/senalActiva.json", json={"esperando": True, "mensaje": msg}, timeout=5)
    except: pass


def esta_pausado():
    try:
        r = requests.get(f"{FIREBASE_URL}/botPausa.json", timeout=5).json()
        if r and isinstance(r, dict):
            return r.get("pausado") == True
    except: pass
    return False


def nombre_mostrado(sym_iq):
    if sym_iq.endswith("-OTC"):
        base = sym_iq.replace("-OTC", "")
        return base[:3] + "/" + base[3:] + " (OTC)"
    return sym_iq[:3] + "/" + sym_iq[3:]


print("══════════════════════════════════════════")
print(" SUPERBOT GCR ELITE — BOT 2 (IQ OPTION) v1.0")
print(" Fuente: IQ Option cuenta DEMO — 8 pares")
print("══════════════════════════════════════════")

if not conectar():
    print(" ❌ No se pudo establecer conexión inicial. Reintentando en 30s...")
    time.sleep(30)
    conectar()

limpiar("Bot IQ iniciado — analizando 24/7...")
ciclo = 0
ultimo_disparo = {}

while True:
    if esta_pausado():
        print(" ⏸ Bot IQ apagado desde la sala...")
        limpiar("Bot apagado — toca ▶ Reanudar en la sala")
        time.sleep(10)
        continue

    ciclo += 1
    ses = sesion_activa()
    hora = datetime.now(TZ_CO).strftime("%H:%M:%S")
    p = get_params()
    pares_iq_ciclo = pares_actuales()
    modo_mercado = "OTC (fin de semana)" if es_fin_de_semana() else "Normal (lun-vie)"
    print(f"\n[{hora}] Ciclo #{ciclo} — {ses} | Mercado: {modo_mercado}")
    print(f" RSI CALL≤{p['RSI_CALL']} PUT≥{p['RSI_PUT']} | DAMOA≥{p['DAMOA']}")

    mejor_senal = None

    for sym_iq in pares_iq_ciclo:
        sym_mostrado = nombre_mostrado(sym_iq)
        print(f" [{sym_mostrado}] consultando IQ Option...")
        df = obtener_datos(sym_iq)
        res = analizar(sym_mostrado, df)

        if res:
            anterior = ultimo_disparo.get(sym_iq)
            if anterior:
                ciclos_pasados = ciclo - anterior["ciclo"]
                limite = MIN_ESPACIADO if res["direccion"] == anterior["dir"] else MIN_CRUZADO
                if ciclos_pasados < limite:
                    print(f" {sym_mostrado}: señal bloqueada por espaciado")
                    res = None
            if res:
                ultimo_disparo[sym_iq] = {"ciclo": ciclo, "dir": res["direccion"]}

        if res:
            print(f"\n ══ [{res['tipo']}][{res['modo']}] {res['par']} {res['direccion']} ══")
            print(f" RSI:{res['rsi']} DAM:{res['damoa']} STK:{res['stoch']} Score:{res['score']} F:{res['fuerza']}")
            ts = str(int(time.time() * 1000))
            res["entrada"] = calcular_entrada()
            try:
                requests.put(f"{FIREBASE_URL}/historial/{ts}.json", json=_safe(res), timeout=5)
            except: pass

            if mejor_senal is None:
                mejor_senal = res
            elif res.get("tipo") == "CONFIRMADA" and mejor_senal.get("tipo") != "CONFIRMADA":
                mejor_senal = res
            elif res.get("tipo") == mejor_senal.get("tipo"):
                try:
                    f_actual = int(str(mejor_senal.get("fuerza", "0/5")).split("/")[0])
                    f_nueva = int(str(res.get("fuerza", "0/5")).split("/")[0])
                    if f_nueva > f_actual:
                        mejor_senal = res
                except (ValueError, IndexError):
                    pass
        else:
            print(f" {sym_mostrado}: sin señal")
        time.sleep(DELAY_PARES)

    if mejor_senal:
        publicar(mejor_senal)
    else:
        limpiar(f"{ses} — Ciclo #{ciclo} — Analizando 8 pares (IQ Option demo)...")

    ahora = datetime.now(TZ_CO)
    segundos_restantes = 60 - ahora.second
    if segundos_restantes < 5:
        segundos_restantes += 60
    espera = max(segundos_restantes - 3, 5)
    print(f"\n Próximo ciclo en {espera}s...")
    time.sleep(espera)
