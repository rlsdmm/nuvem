"""Consulta a previsão de Miguelópolis e avisa os celulares cadastrados quando há risco de tempestade.

Roda de hora em hora no GitHub Actions. Segredos, nas variáveis de ambiente:
  VAPID_PRIVATE_KEY   chave de envio
  PUSH_SUBSCRIPTIONS  lista JSON com os códigos gerados pelo botão "Ativar alertas" do app
Uso: verificar.py <arquivo de estado>; com TESTE=true só manda uma notificação de teste.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

LUGAR = {"nome": "Miguelópolis", "lat": -20.17944, "lon": -48.03194}
APP = "https://rlsdmm.github.io/nuvem/"
TROVOADA = (95, 96, 99)
CHUVA_FORTE_MM = 5    # mm/h junto com trovoada
RAJADA_KMH = 50
HORAS_A_FRENTE = 36
PERTO_HORAS = 3       # segundo aviso, quando a tempestade está a poucas horas
SILENCIO = (22, 6)    # sem notificação das 22h às 6h, na hora local
PULSO_DIAS = 30       # grava o estado para o GitHub não pausar a tarefa por inatividade


def previsao():
    p = {"latitude": LUGAR["lat"], "longitude": LUGAR["lon"], "timezone": "America/Sao_Paulo", "current": "temperature_2m",
         "hourly": "weather_code,precipitation,wind_gusts_10m", "forecast_hours": HORAS_A_FRENTE + 1}
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(p)
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except OSError as e:
            print(f"Previsão indisponível (tentativa {tentativa + 1}): {e}")
            if tentativa == 2:
                raise
            time.sleep(30)


def horas_de_risco(d):
    """Horas futuras com risco, a partir da hora atual."""
    h, agora = d["hourly"], d["current"]["time"][:13]
    fim = datetime.fromisoformat(d["current"]["time"]) + timedelta(hours=HORAS_A_FRENTE)
    risco = []
    for t, c, chuva, rajada in zip(h["time"], h["weather_code"], h["precipitation"], h["wind_gusts_10m"]):
        if t[:13] < agora or datetime.fromisoformat(t) > fim:
            continue
        trovoada = c in TROVOADA and (chuva or 0) >= CHUVA_FORTE_MM
        if trovoada or (rajada or 0) >= RAJADA_KMH:
            risco.append({"t": datetime.fromisoformat(t), "trovoada": trovoada, "rajada": rajada or 0})
    return risco


def decidir(d, estado):
    """Devolve o próximo alerta a enviar, ou None. Cada dia recebe no máximo um aviso e um aviso de perto."""
    agora = datetime.fromisoformat(d["current"]["time"])
    if agora.hour >= SILENCIO[0] or agora.hour < SILENCIO[1]:
        return None
    por_dia = {}
    for x in horas_de_risco(d):
        por_dia.setdefault(x["t"].date(), []).append(x)
    enviados = estado.get("enviados", [])
    for dia in sorted(por_dia):
        horas = por_dia[dia]
        faltam = (horas[0]["t"] - agora).total_seconds() / 3600
        etapa = "perto" if faltam <= PERTO_HORAS else "aviso"
        chave = f"{dia.isoformat()}:{etapa}"
        if chave not in enviados:
            return {"chave": chave, **mensagem(dia, horas, agora, etapa)}
    return None


def mensagem(dia, horas, agora, etapa):
    quando = {0: "Hoje", 1: "Amanhã", 2: "Depois de amanhã"}[(dia - agora.date()).days]
    inicio = horas[0]["t"]
    partes = []
    if any(x["trovoada"] for x in horas):
        partes.append("trovoada com chuva forte")
    rajada = max(x["rajada"] for x in horas)
    if rajada >= RAJADA_KMH:
        partes.append(f"rajadas de até {round(rajada)} km/h")
    if inicio <= agora:
        horario = f"{quando}, agora"
    else:
        horario = f"{quando}, a partir das {inicio.hour}h"
    titulo = f"Tempestade próxima em {LUGAR['nome']}" if etapa == "perto" else f"Risco de tempestade em {LUGAR['nome']}"
    return {"titulo": titulo, "corpo": f"{horario}: {' e '.join(partes)}. Evite ficar na água.", "url": APP}


def enviar(alerta):
    """Manda para todos os celulares; devolve quantos receberam e quantos falharam."""
    from pywebpush import WebPushException, webpush
    inscricoes = json.loads(os.environ["PUSH_SUBSCRIPTIONS"])
    corpo = json.dumps({k: alerta[k] for k in ("titulo", "corpo", "url")} | {"tag": alerta["chave"]}, ensure_ascii=False)
    certos = falhas = 0
    for k, inscricao in enumerate(inscricoes):
        try:
            webpush(inscricao, corpo, vapid_private_key=os.environ["VAPID_PRIVATE_KEY"], vapid_claims={"sub": "https://rlsdmm.github.io"}, ttl=6 * 3600,
                    headers={"Urgency": "high"}, timeout=30)
            certos += 1
        except WebPushException as e:  # o endereço de envio é segredo: não vai para o registro
            falhas += 1
            print(f"Celular {k + 1}: falhou com HTTP {getattr(e.response, 'status_code', '?')}. Se for 404 ou 410, cadastre o aparelho de novo.")
    return certos, falhas


def main():
    arquivo = sys.argv[1]
    if os.environ.get("TESTE") == "true":
        certos, falhas = enviar({"chave": "teste", "titulo": "Nuvem: teste de alerta",
                                 "corpo": "Se você está vendo isto, os alertas de tempestade estão funcionando.", "url": APP})
        print(f"Teste: {certos} enviados, {falhas} falhas")
        return 1 if falhas or not certos else 0

    try:
        with open(arquivo, encoding="utf-8") as f:
            estado = json.load(f)
    except (OSError, ValueError):
        estado = {}
    d = previsao()
    hoje = d["current"]["time"][:10]
    print("Horas de risco:", [x["t"].isoformat() for x in horas_de_risco(d)])

    falhas = 0
    alerta = decidir(d, estado)
    if alerta:
        print("Alerta:", alerta["titulo"], "|", alerta["corpo"])
        certos, falhas = enviar(alerta)
        print(f"{certos} enviados, {falhas} falhas")
        if certos:
            estado.setdefault("enviados", []).append(alerta["chave"])

    estado["enviados"] = [k for k in estado.get("enviados", []) if k[:10] >= hoje]
    pulso = estado.get("pulso")
    if not pulso or date.fromisoformat(hoje) - date.fromisoformat(pulso) >= timedelta(days=PULSO_DIAS):
        estado["pulso"] = hoje
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    return 1 if falhas else 0  # falha aparece no GitHub e gera e-mail: alerta perdido não pode passar em silêncio


if __name__ == "__main__":
    sys.exit(main())
