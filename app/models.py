from flask_login import UserMixin
from sqlalchemy.dialects.sqlite import JSON
from .extensions import db
import uuid
import qrcode
from flask import send_file
from io import BytesIO
from datetime import datetime
import pytz

# ---------------- Funções auxiliares ----------------

def hora_brasil():
    return datetime.now(pytz.timezone("America/Sao_Paulo"))

def gerar_qrcode_pix(payload):
    qr = qrcode.make(payload)
    img_io = BytesIO()
    qr.save(img_io, 'PNG')
    img_io.seek(0)
    return img_io

# ---------------- Modelos principais ----------------

class Admin(UserMixin, db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)

class Cliente(UserMixin, db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    cpf_cnpj = db.Column(db.String(18), nullable=False)
    telefone = db.Column(db.String(25))
    endereco = db.Column(db.String(200))
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(50))
    cep = db.Column(db.String(15))
    pedidos = db.relationship('Pedido', backref='cliente', lazy=True)

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)

class Colecao(db.Model):
    __tablename__ = 'colecoes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True)
    descricao = db.Column(db.Text)
    imagem = db.Column(db.String(255))
    ativa = db.Column(db.Boolean, default=True)

    produtos = db.relationship('Produto', back_populates='colecao')


class Produto(db.Model):
    __tablename__ = 'produtos'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=True, unique=True)
    nome = db.Column(db.String(120), nullable=False)
    cores_imagens = db.Column(JSON, nullable=True)
    descricao = db.Column(db.Text)
    descricao_curta = db.Column(db.String(255))

    preco_par = db.Column(db.Float, nullable=False)
    preco_parcelado = db.Column(db.Float, nullable=True)
    preco_caixa = db.Column(db.Float)

    qtd_minima = db.Column(db.Integer, default=1)
    imagem_principal = db.Column(db.String(255))

    grade = db.Column(JSON, nullable=False)
    peso = db.Column(db.Float, nullable=False, default=0.5)

    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'))
    categoria = db.relationship('Categoria', backref='produtos')

    destaque = db.Column(db.Boolean, default=False)
    ativo = db.Column(db.Boolean, default=True)

    colecao_id = db.Column(db.Integer, db.ForeignKey('colecoes.id'))
    colecao = db.relationship('Colecao', back_populates='produtos')

    cor = db.Column(db.String(50))
    tipo_salto = db.Column(db.String(50))

    def __repr__(self):
        return f'<Produto {self.nome}>'

class ProdutoImagem(db.Model):
    __tablename__ = 'produto_imagens'
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    imagem = db.Column(db.String(150), nullable=False)

class Pedido(db.Model):
    __tablename__ = 'pedidos'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'))
    data = db.Column(db.DateTime, default=hora_brasil)
    frete_valor = db.Column(db.Float, default=0)
    frete_transportadora = db.Column(db.String(50))
    frete_prazo = db.Column(db.String(50))
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), default='Aguardando pagamento')
    nf_emitida = db.Column(db.Boolean, default=False)
    numero_nf = db.Column(db.String(50))
    itens = db.relationship('ItemPedido', backref='pedido', lazy=True)

class ItemPedido(db.Model):
    __tablename__ = 'itens_pedido'
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    nome_produto = db.Column(db.String(120))
    cor = db.Column(db.String(100))
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Float, nullable=False)
    preco_total = db.Column(db.Float, nullable=False)
    tamanho = db.Column(db.String(10))
    imagem_produto = db.Column(db.String(150))

class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100))
    subtitulo = db.Column(db.String(200))
    imagem = db.Column(db.String(150))  # Caminho do arquivo no static
    link_botao = db.Column(db.String(200))
    texto_botao = db.Column(db.String(50))
    ordem = db.Column(db.Integer, default=1)
    ativo = db.Column(db.Boolean, default=True)

# ---------------- Login ----------------

def get_user(user_id):
    user = Admin.query.get(user_id)
    if not user:
        user = Cliente.query.get(user_id)
    return user
