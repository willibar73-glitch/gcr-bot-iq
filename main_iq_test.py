"""
PRUEBA DE CONEXIÓN — IQ Option (Bot 2, Etapa 1)
Este script SOLO prueba que la cuenta conecta y trae velas.
No analiza nada todavía, no manda nada a Firebase.

Lee las credenciales desde variables de entorno (NUNCA escritas aquí):
  IQ_EMAIL    -> tu correo de IQ Option
  IQ_PASSWORD -> tu contraseña de IQ Option
"""
import subprocess, sys, os, time

# ── Auto-instalador ──
def instalar(pkg, origen=None):
    try:
        __import__(pkg)
    except ImportError:
        objetivo = origen or pkg
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                                "--no-warn-script-location", "--disable-pip-version-check", objetivo])

instalar("websocket", "websocket-client")
instalar("requests")
try:
    import iqoptionapi
except ImportError:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--quiet",
        "--no-warn-script-location", "--disable-pip-version-check",
        "git+https://github.com/iqoptionapi/iqoptionapi.git"
    ])

from iqoptionapi.stable_api import IQ_Option

EMAIL = os.environ.get("IQ_EMAIL")
PASSWORD = os.environ.get("IQ_PASSWORD")

if not EMAIL or not PASSWORD:
    print("❌ FALTAN credenciales. Debes configurar IQ_EMAIL e IQ_PASSWORD")
    print("   en las Variables de Railway (pestaña Variables del servicio).")
    sys.exit(1)

print("══════════════════════════════════════════")
print(" PRUEBA DE CONEXIÓN — IQ OPTION")
print("══════════════════════════════════════════")
print(f" Conectando con: {EMAIL[:3]}***{EMAIL[-10:]}")  # nunca mostramos el correo completo en logs

Iq = IQ_Option(EMAIL, PASSWORD)
ok, razon = Iq.connect()

if not ok:
    print(f" ❌ No se pudo conectar: {razon}")
    sys.exit(1)

print(" ✅ Conexión exitosa")

# Forzar modo cuenta DEMO (práctica) — nunca cuenta real
try:
    Iq.change_balance("PRACTICE")
    print(" ✅ Cuenta cambiada a modo PRACTICE (demo)")
except Exception as e:
    print(f" ⚠️ No se pudo confirmar el cambio a demo: {e}")

try:
    perfil = Iq.get_profile_ansyc()
    print(f" Perfil obtenido: {perfil is not None}")
except Exception as e:
    print(f" ⚠️ get_profile_ansyc falló (no crítico): {e}")

# Traer 5 velas de 1 minuto de EUR/USD como prueba
print("\n Solicitando 5 velas de 1 minuto de EURUSD...")
try:
    velas = Iq.get_candles("EURUSD", 60, 5, time.time())
    if velas:
        print(f" ✅ {len(velas)} velas recibidas:")
        for v in velas:
            print(f"   {time.strftime('%H:%M:%S', time.localtime(v['from']))} "
                  f"O:{v['open']} C:{v['close']} H:{v['max']} L:{v['min']}")
    else:
        print(" ⚠️ No se recibieron velas (puede ser horario de mercado cerrado o símbolo inválido)")
except Exception as e:
    print(f" ❌ Error al pedir velas: {e}")

print("\n══════════════════════════════════════════")
print(" PRUEBA TERMINADA")
print("══════════════════════════════════════════")
