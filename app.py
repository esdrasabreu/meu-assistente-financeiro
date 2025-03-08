from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Configurações iniciais
app = Flask(__name__)

# Configurações do Gemini
GEMINI_API_KEY = "AIzaSyCJGAapg7tKgRCGk4EEhYUoSVF-e4FINhk"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

# Configurações do Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS_FILE = "credenciais.json"  # Arquivo de credenciais do Google Sheets
SPREADSHEET_ID = "10D0O13KzytlECgma6s-Yiz6JNhOjemDMZbOp0To2RDY"  # ID da planilha do Google Sheets

# Autenticação no Google Sheets
creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# Função para ler a meta de gastos do Google Sheets
def ler_meta_gastos():
    try:
        meta = sheet.acell("F1").value
        return float(meta) if meta else 1000.00
    except Exception as e:
        print("Erro ao ler a meta de gastos:", str(e))
        return 1000.00

# Função para salvar a meta de gastos no Google Sheets
def salvar_meta_gastos(meta):
    try:
        sheet.update_acell("F1", str(meta))
    except Exception as e:
        print("Erro ao salvar a meta de gastos:", str(e))

# Inicializa a meta de gastos
meta_gastos = ler_meta_gastos()

# Função para interagir com o Gemini
def interagir_com_gemini(mensagem, contexto=None):
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "contents": [
            {
                "parts": [
                    {"text": f"{contexto}\n\n{mensagem}" if contexto else mensagem}
                ]
            }
        ]
    }
    response = requests.post(GEMINI_API_URL, json=data, headers=headers)
    if response.status_code == 200:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    else:
        print("Erro na API do Gemini:", response.status_code, response.text)
        return "Desculpe, ocorreu um erro ao processar sua mensagem."

# Função para salvar transações no Google Sheets
def salvar_transacao(valor, tipo, categoria, descricao):
    data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([data, valor, tipo, categoria, descricao])

# Função para consultar transações no Google Sheets
def consultar_transacoes(mes=None, tipo=None):
    try:
        dados = sheet.get_all_records()
        if mes:
            dados = [transacao for transacao in dados if datetime.strptime(transacao["Data"], "%Y-%m-%d %H:%M:%S").month == mes]
        if tipo:
            dados = [transacao for transacao in dados if transacao["Tipo"].lower() == tipo.lower()]
        return dados
    except Exception as e:
        print("Erro ao consultar transações:", str(e))
        return []

# Rota para receber mensagens do Twilio
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.form.get("Body")
    from_number = request.form.get("From")
    response = MessagingResponse()

    global meta_gastos

    # Contexto para o Gemini
    contexto = f"""
    Você é um assistente financeiro que ajuda os usuários a gerenciar suas finanças.
    Aqui estão as funcionalidades disponíveis:
    - Registrar uma receita (ex: 'receita 2000 salário')
    - Consultar valor total de gastos (ex: 'qual é o valor total de gasto?')
    - Consultar gastos do mês (ex: 'qual é o valor total desse mês?')
    - Consultar categoria com mais gastos (ex: 'qual categoria teve mais gastos?')
    - Listar todas as compras (ex: 'listar todas as compras')
    - Definir meta de gastos (ex: 'definir meta de gastos 1000')

    Meta atual de gastos: R${meta_gastos:.2f}
    """

    # Processar mensagem de texto
    if incoming_msg:
        try:
            resposta_gemini = interagir_com_gemini(incoming_msg, contexto)
            resposta = resposta_gemini

            # Verifica se a resposta do Gemini indica uma ação específica
            if "registrar receita" in resposta_gemini.lower():
                valor, descricao = resposta_gemini.split("|")
                valor = float(valor.strip())
                descricao = descricao.strip()
                salvar_transacao(valor, "receita", "Receita", descricao)
                resposta = f"Receita de R${valor:.2f} registrada com sucesso."
            elif "consultar valor total de gastos" in resposta_gemini.lower():
                gastos = consultar_transacoes(tipo="gasto")
                if gastos:
                    total = sum(float(gasto["Valor"]) for gasto in gastos)
                    resposta = f"O valor total de gastos é R${total:.2f}."
                    if total > meta_gastos:
                        resposta += f"\nVocê ultrapassou sua meta de gastos de R${meta_gastos:.2f} em R${total - meta_gastos:.2f}."
                    else:
                        resposta += f"\nFaltam R${meta_gastos - total:.2f} para atingir sua meta de gastos de R${meta_gastos:.2f}."
                else:
                    resposta = "Nenhum gasto registrado até o momento."
            elif "consultar gastos do mês" in resposta_gemini.lower():
                mes_atual = datetime.now().month
                gastos = consultar_transacoes(mes=mes_atual, tipo="gasto")
                if gastos:
                    total = sum(float(gasto["Valor"]) for gasto in gastos)
                    resposta = f"O valor total de gastos deste mês é R${total:.2f}."
                else:
                    resposta = "Nenhum gasto registrado para este mês."
            elif "consultar categoria com mais gastos" in resposta_gemini.lower():
                gastos = consultar_transacoes(tipo="gasto")
                if gastos:
                    categorias = {}
                    for gasto in gastos:
                        categoria = gasto["Categoria"]
                        valor = float(gasto["Valor"])
                        if categoria in categorias:
                            categorias[categoria] += valor
                        else:
                            categorias[categoria] = valor
                    categoria_mais_gastos = max(categorias, key=categorias.get)
                    resposta = f"A categoria com mais gastos é **{categoria_mais_gastos}** com R${categorias[categoria_mais_gastos]:.2f}."
                else:
                    resposta = "Nenhum gasto registrado até o momento."
            elif "listar todas as compras" in resposta_gemini.lower():
                gastos = consultar_transacoes(tipo="gasto")
                if gastos:
                    resposta = "Lista de todas as compras:\n"
                    for gasto in gastos:
                        resposta += f"- {gasto['Descrição']}: R${gasto['Valor']:.2f} ({gasto['Categoria']})\n"
                else:
                    resposta = "Nenhuma compra registrada até o momento."
            elif "definir meta de gastos" in resposta_gemini.lower():
                try:
                    nova_meta = float(resposta_gemini.split("definir meta de gastos")[1].strip())
                    meta_gastos = nova_meta
                    salvar_meta_gastos(meta_gastos)
                    resposta = f"Meta de gastos definida para R${meta_gastos:.2f}."
                except:
                    resposta = "Formato inválido. Use: 'definir meta de gastos X'."
        except Exception as e:
            resposta = f"Erro ao processar a mensagem: {str(e)}"
    else:
        resposta = "Envie uma mensagem para interagir com o assistente."

    response.message(resposta)
    return str(response)

if __name__ == "__main__":
    app.run(debug=True)