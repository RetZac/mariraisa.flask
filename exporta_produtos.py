from app import create_app
from app.models import Produto
import csv

app = create_app()
with app.app_context():
    produtos = Produto.query.all()
    with open('produtos_exportados.csv', 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['id', 'codigo', 'nome', 'descricao', 'preco_vista', 'preco_parcelado', 'caixa_qtd', 'tamanhos', 'estoque_por_tamanho', 'foto'])
        for p in produtos:
            writer.writerow([p.id, p.codigo, p.nome, p.descricao, p.preco_vista, p.preco_parcelado, p.caixa_qtd, p.tamanhos, p.estoque_por_tamanho, p.foto])
print("Exportação concluída!")
