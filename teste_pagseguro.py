import requests

# 👇 Use exatamente esses dados
email = "lojamariaraisa@hotmail.com"
token = "C06FAAFA21A1481E83181A27DCB52097"

# 👇 Dados do pedido – itemAmount com ponto (não vírgula)
data = {
    "email": email,
    "token": token,
    "currency": "BRL",
    "itemId1": "1",
    "itemDescription1": "Sandália Teste",
    "itemAmount1": "50.00",  # Use ponto
    "itemQuantity1": "1",
    "reference": "pedido123"
}

headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

# 👇 URL correta do sandbox
response = requests.post(
    "https://ws.sandbox.pagseguro.uol.com.br/v2/checkout",
    data=data,
    headers=headers,
    timeout=30
)

print("Status:", response.status_code)
print("Resposta:", response.text)