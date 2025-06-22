import os
import sqlite3

# Caminho do banco e da pasta de imagens
caminho_banco = 'C:/Users/isacn/Desktop/Projeto Site/instance/produtos.db'
pasta_imagens = 'C:/Users/isacn/Desktop/Projeto Site/app/static/images'

# Conecta ao banco
conn = sqlite3.connect(caminho_banco)
cursor = conn.cursor()

# Pega todas as imagens do banco
cursor.execute("SELECT imagem FROM produto_imagens")
imagens_banco = set([linha[0] for linha in cursor.fetchall()])

# Lista todos os arquivos da pasta
imagens_pasta = set(os.listdir(pasta_imagens))

# Diferenças
faltando_na_pasta = imagens_banco - imagens_pasta
sobrando_na_pasta = imagens_pasta - imagens_banco

# Resultado
print("📦 Imagens faltando na pasta (estão no banco, mas não na pasta):")
for img in faltando_na_pasta:
    print(f" - {img}")

print("\n🗃️ Imagens que estão na pasta mas não estão no banco:")
for img in sobrando_na_pasta:
    print(f" - {img}")
