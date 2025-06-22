import requests

def consultar_endereco(cep):
    try:
        response = requests.get(f"https://viacep.com.br/ws/{cep}/json/")
        if response.status_code == 200:
            data = response.json()
            if "erro" not in data:
                endereco = f"{data['logradouro']}, {data['bairro']} - {data['localidade']}/{data['uf']}"
                return endereco
    except Exception as e:
        print("Erro ao consultar o CEP:", e)
    return None
