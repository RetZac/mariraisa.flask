import pandas as pd
import os
from flask import current_app
import requests

def get_estado_por_cep(cep):
    if cep.startswith('01') or cep.startswith('02'):
        return 'SP'
    elif cep.startswith('20') or cep.startswith('21'):
        return 'RJ'
    elif cep.startswith('30') or cep.startswith('31'):
        return 'MG'
    else:
        return 'OUTROS'

def listar_opcoes_frete(cep_destino, peso_total):
    uf = get_estado_por_cep(cep_destino)
    caminho_csv = os.path.join(current_app.root_path, 'static', 'tabelas', 'frete_tabela.csv')

    if not os.path.exists(caminho_csv):
        print("[AVISO] Arquivo de frete não encontrado.")
        return []

    try:
        tabela = pd.read_csv(caminho_csv)
    except Exception as e:
        print(f"[ERRO] Falha ao ler CSV de frete: {e}")
        return []

    colunas_esperadas = {'UF', 'Transportadora', 'Valor', 'Prazo_dias', 'Peso_Mín_kg', 'Peso_Máx_kg'}
    if not colunas_esperadas.issubset(set(tabela.columns)):
        print("[ERRO] Tabela de frete inválida.")
        return []

    opcoes = tabela[
        (tabela['UF'] == uf) &
        (tabela['Peso_Mín_kg'] <= peso_total) &
        (tabela['Peso_Máx_kg'] >= peso_total)
    ]

    lista = []
    for _, linha in opcoes.iterrows():
        lista.append({
            'transportadora': linha['Transportadora'],
            'valor': float(linha['Valor']),
            'prazo': f"{int(linha['Prazo_dias'])} dias úteis"
        })

    return lista

def consultar_endereco(cep):
    try:
        response = requests.get(f"https://viacep.com.br/ws/{cep}/json/")
        if response.status_code == 200:
            dados = response.json()
            if "erro" not in dados:
                return f"{dados.get('logradouro', '')}, {dados.get('bairro', '')}, {dados.get('localidade', '')} - {dados.get('uf', '')}"
    except Exception as e:
        print(f"Erro ao consultar endereço: {e}")
    return None
