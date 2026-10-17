import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import schedule
from dotenv import load_dotenv

# ===== CONFIGURAÇÕES =====
load_dotenv()
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ORIGENS = {
    "BSB": "Brasília",
    "GRU": "São Paulo (Guarulhos)",
}
DESTINO = "BER"  # Berlim
DATAS_IDA = ["2027-09-08", "2027-09-09"]  # formato AAAA-MM-DD
DATA_VOLTA = "2027-09-26"
HORARIOS = ["09:00", "21:00"]

ARQUIVO_HISTORICO = Path("historico_precos.json")


# ===== BUSCA DE VOOS =====
def buscar_voo_mais_barato(origem, data_ida):
    """Consulta o Google Flights (via SerpApi) e devolve o voo mais barato."""
    params = {
        "engine": "google_flights",
        "departure_id": origem,
        "arrival_id": DESTINO,
        "outbound_date": data_ida,
        "return_date": DATA_VOLTA,
        "type": "1",          # 1 = ida e volta
        "adults": "1",
        "currency": "BRL",
        "hl": "pt",
        "gl": "br",
        "api_key": SERPAPI_KEY,
    }
    resposta = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    resposta.raise_for_status()
    dados = resposta.json()

    voos = dados.get("best_flights", []) + dados.get("other_flights", [])
    voos = [v for v in voos if "price" in v]
    if not voos:
        return None

    mais_barato = min(voos, key=lambda v: v["price"])
    companhias = sorted({trecho["airline"] for trecho in mais_barato["flights"]})
    return {
        "preco": mais_barato["price"],
        "companhias": ", ".join(companhias),
        "escalas": len(mais_barato.get("layovers", [])),
        "duracao_h": round(mais_barato.get("total_duration", 0) / 60, 1),
    }


def link_skyscanner(origem, data_ida):
    """Monta o link de busca do Skyscanner (datas no formato AAMMDD)."""
    ida = datetime.strptime(data_ida, "%Y-%m-%d").strftime("%y%m%d")
    volta = datetime.strptime(DATA_VOLTA, "%Y-%m-%d").strftime("%y%m%d")
    return (f"https://www.skyscanner.com.br/transporte/passagens-aereas/"
            f"{origem.lower()}/{DESTINO.lower()}/{ida}/{volta}/")


# ===== HISTÓRICO (para comparar com a busca anterior) =====
def carregar_historico():
    if ARQUIVO_HISTORICO.exists():
        return json.loads(ARQUIVO_HISTORICO.read_text(encoding="utf-8"))
    return {}


def salvar_historico(historico):
    ARQUIVO_HISTORICO.write_text(json.dumps(historico, indent=2), encoding="utf-8")


# ===== TELEGRAM =====
def enviar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resposta = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    if not resposta.ok:
        raise Exception(f"Telegram recusou a mensagem: {resposta.text}")


# ===== TAREFA PRINCIPAL =====
def executar_busca():
    print(f"[{datetime.now():%d/%m %H:%M}] Iniciando busca...")
    historico = carregar_historico()
    linhas = [f"✈️ <b>Passagens para Berlim</b> — {datetime.now():%d/%m/%Y %H:%M}",
              f"Volta: {datetime.strptime(DATA_VOLTA, '%Y-%m-%d'):%d/%m/%Y}\n"]

    for codigo, cidade in ORIGENS.items():
        for data_ida in DATAS_IDA:
            chave = f"{codigo}-{data_ida}"
            data_br = datetime.strptime(data_ida, "%Y-%m-%d").strftime("%d/%m/%Y")
            try:
                voo = buscar_voo_mais_barato(codigo, data_ida)
            except Exception as erro:
                linhas.append(f"⚠️ {cidade} ({data_br}): erro na busca — {erro}\n")
                continue

            if voo is None:
                linhas.append(f"❔ {cidade} → Berlim, ida {data_br}: sem resultados ainda\n")
                continue

            # Compara com o preço da última busca
            anterior = historico.get(chave)
            variacao = ""
            if anterior:
                diferenca = voo["preco"] - anterior
                if diferenca < 0:
                    variacao = f" 📉 caiu R$ {abs(diferenca):,.0f}"
                elif diferenca > 0:
                    variacao = f" 📈 subiu R$ {diferenca:,.0f}"
            historico[chave] = voo["preco"]

            linhas.append(
                f"🛫 <b>{cidade} → Berlim</b> | ida {data_br}\n"
                f"💰 <b>R$ {voo['preco']:,.0f}</b>{variacao}\n"
                f"🏢 {voo['companhias']} | {voo['escalas']} escala(s) | {voo['duracao_h']}h\n"
                f"🔗 <a href='{link_skyscanner(codigo, data_ida)}'>Ver no Skyscanner</a>\n"
            )

    salvar_historico(historico)
    enviar_telegram("\n".join(linhas))
    print("Alerta enviado!")


# ===== AGENDAMENTO =====
if __name__ == "__main__":
    if "--agora" in sys.argv:
        executar_busca()  # roda uma vez só (bom para testar)
    else:
        for horario in HORARIOS:
            schedule.every().day.at(horario).do(executar_busca)
        print(f"Agente rodando. Alertas às {', '.join(HORARIOS)}. Ctrl+C para parar.")
        while True:
            schedule.run_pending()
            time.sleep(30)