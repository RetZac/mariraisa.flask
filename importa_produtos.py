from app import create_app, db
from app.models import Produto
import csv

app = create_app()
with app.app_context():
    with open('produtos_exportados.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            produto = Produto(
                codigo=row['codigo'],
                nome=row['nome'],
                descricao=row['descricao'],
                preco_vista=float(row['preco_vista']),
                preco_parcelado=float(row['preco_parcelado']),
                caixa_qtd=int(row['caixa_qtd']),
                tamanhos=row['tamanhos'],
                estoque_por_tamanho=row['estoque_por_tamanho'],
                foto=row['foto']
            )
            db.session.add(produto)
        db.session.commit()
print("Importação concluída!")
