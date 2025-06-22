from flask import (
    Blueprint, render_template, request, flash, session, abort, jsonify, current_app, url_for, redirect
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from .models import db, Admin, Cliente, Produto, Categoria, ProdutoImagem, ItemPedido, Colecao, Banner
from datetime import datetime
import pytz, os, base64, qrcode
from qrcode.constants import ERROR_CORRECT_M
from dotenv import load_dotenv
from app.utils.frete import listar_opcoes_frete, consultar_endereco
fuso_brasil = pytz.timezone("America/Sao_Paulo")
data=datetime.now(fuso_brasil)

load_dotenv()  # Carrega variáveis do .env

PAGSEGURO_EMAIL = os.getenv("PAGSEGURO_EMAIL")
PAGSEGURO_TOKEN = os.getenv("PAGSEGURO_TOKEN")

routes = Blueprint('routes', __name__)


# Função de cálculo CRC16 (obrigatório para Pix dinâmico)
def calcular_crc16(payload):
    polinomio = 0x1021
    resultado = 0xFFFF
    for byte in payload.encode():
        resultado ^= byte << 8
        for _ in range(8):
            if resultado & 0x8000:
                resultado = (resultado << 1) ^ polinomio
            else:
                resultado <<= 1
            resultado &= 0xFFFF
    return format(resultado, '04X')

# Função que gera o payload Pix

def gerar_payload_pix(chave, nome, cidade, valor):
    gui = "br.gov.bcb.pix"
    merchant = f"00{len(gui):02}{gui}01{len(chave):02}{chave}"
    merchant_field = f"26{len(merchant):02}{merchant}"
    nome = nome[:25]
    cidade = cidade[:15]
    valor_str = f"{valor:.2f}"
    txid = "***"  # ← fixo e válido para QR estático
    txid_field = f"0503{txid}"
    additional_field = f"62{len(txid_field):02}{txid_field}"

    payload_sem_crc = (
        "000201"
        "010212"
        f"{merchant_field}"
        "52040000"
        "5303986"
        f"54{len(valor_str):02}{valor_str}"
        "5802BR"
        f"59{len(nome):02}{nome}"
        f"60{len(cidade):02}{cidade}"
        f"{additional_field}"
        "6304"
    )
    crc = calcular_crc16(payload_sem_crc)
    return payload_sem_crc + crc



# Rota para exibir QR Code de pagamento Pix
@routes.route('/pagamento/pix/<int:pedido_id>')
@login_required
def pagamento_pix(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)

    # Verifica se o usuário pode acessar o pedido
    if not isinstance(current_user, Admin) and pedido.cliente_id != current_user.id:
        abort(403)

    # Verifica se o total do pedido está correto
    if not pedido.total or pedido.total is None:
        flash("Erro: Valor total do pedido não definido.")
        return redirect(url_for('routes.index'))

    chave_pix = "19715451000133"  # 🔑 Substitua pela sua chave Pix válida
    nome_recebedor = "Maria Raisa"
    cidade = "JAU"

    try:
        payload = gerar_payload_pix(
            chave=chave_pix,
            nome=nome_recebedor,
            cidade=cidade,
            valor=float(pedido.total)  # Garante que é número
        )
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar payload Pix: {e}")
        flash("Erro ao gerar código Pix.")
        return redirect(url_for('routes.index'))

    # Gera o QR Code em memória
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    qr_code_base64 = base64.b64encode(buffer.read()).decode('utf-8')

    # ✅ Envia o e-mail de confirmação (se desejar deixar aqui)
    try:
        from app.utils.email import enviar_email_confirmacao
        enviar_email_confirmacao(pedido.cliente.email, pedido)
    except Exception as e:
        current_app.logger.warning(f"Erro ao enviar e-mail: {e}")

    return render_template("pagamento_pix.html",
                           pedido=pedido,
                           qr_code_base64=qr_code_base64,
                           chave_pix=chave_pix,
                           payload_pix=payload)



import requests
import xml.etree.ElementTree as ET

@routes.route('/pagamento/pagseguro/<int:pedido_id>')
@login_required
def pagamento_pagseguro(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)

    data = {
        "email": PAGSEGURO_EMAIL,
        "token": PAGSEGURO_TOKEN,
        "currency": "BRL",
        "itemId1": "001",
        "itemDescription1": f"Pedido {pedido.id}",
        "itemAmount1": "%.2f" % pedido.total,  # ex: "49.90"
        "itemQuantity1": "1",
        "reference": str(pedido.id)
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }

    try:
        response = requests.post(
            "https://ws.pagseguro.uol.com.br/v2/checkout",  # ✅ produção
            data=data,
            headers=headers,
            timeout=60
        )

        if response.status_code != 200:
            return f"Erro PagSeguro: {response.status_code}", 500

        tree = ET.fromstring(response.text)
        code = tree.find("code").text

        # ✅ Redireciona para o ambiente de produção
        return redirect(f"https://pagseguro.uol.com.br/v2/checkout/payment.html?code={code}")


    except Exception as e:
        current_app.logger.error(f"Erro PagSeguro: {e}")
        return f"Erro interno: {e}", 500
    from app.utils.email import enviar_email_confirmacao
    enviar_email_confirmacao(pedido.cliente.email, pedido)

    return render_template('pedido_confirmado.html', pedido=pedido)

import mercadopago
from flask import redirect, url_for
from flask_login import login_required
from .models import Pedido

@routes.route('/pagamento/mercadopago/<int:pedido_id>')
@login_required
def pagamento_mercadopago(pedido_id):
    from app.models import Pedido  # Garante o import correto

    pedido = Pedido.query.get_or_404(pedido_id)

    # Verifica se o pedido pertence ao cliente logado
    if not isinstance(current_user, Admin) and pedido.cliente_id != current_user.id:
        abort(403)

    # Token de teste do Mercado Pago
    sdk = mercadopago.SDK("APP_USR-5397203506997346-052915-89e05d7712d9ac3a02e892e850d8a89f-2464272947")

    preference_data = {
        "items": [
            {
                "title": f"Pedido #{pedido.id}",
                "quantity": 1,
                "unit_price": float(pedido.total)
            }
        ],
        "back_urls": {
            "success": f"https://4b12-2804-7f0-aa17-f549-498a-9c7c-8798-7043.ngrok-free.app/pagamento/sucesso",
            "failure": f"https://4b12-2804-7f0-aa17-f549-498a-9c7c-8798-7043.ngrok-free.app/pagamento/erro",
            "pending": f"https://4b12-2804-7f0-aa17-f549-498a-9c7c-8798-7043.ngrok-free.app/pagamento/pendente"
        },
        "auto_return": "approved",
        "external_reference": str(pedido.id)
    }

    try:
        preference_response = sdk.preference().create(preference_data)
        init_point = preference_response["response"].get("init_point")

        if not init_point:
            current_app.logger.error("Erro ao gerar preferência Mercado Pago")
            flash("Erro ao iniciar pagamento com Mercado Pago.", "danger")
            return redirect(url_for('routes.pedido_detalhe', pedido_id=pedido.id))

        session["pedido_id"] = pedido.id
        return redirect(init_point)

    except Exception as e:
        current_app.logger.error(f"Erro Mercado Pago: {e}")
        flash("Erro ao processar pagamento com Mercado Pago.", "danger")
        return redirect(url_for('routes.pedido_detalhe', pedido_id=pedido.id))




# AUTENTICAÇÃO
@routes.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')

        cliente = Cliente.query.filter_by(email=email).first()
        if cliente and check_password_hash(cliente.senha, senha):
            login_user(cliente)
            return redirect(url_for('routes.area_cliente'))

        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.senha, senha):
            login_user(admin)
            return redirect(url_for('routes.painel_admin'))

        flash('E-mail ou senha inválidos.', 'danger')
        # Volta para home com modal de login aberto
        return redirect(url_for('routes.index') + '?modal=login_cliente')

    # Se for GET, não renderiza login.html — redireciona para home com modal
    return redirect(url_for('routes.index') + '?modal=login_cliente')





@routes.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('routes.index'))

@routes.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = generate_password_hash(request.form['senha'])
        cpf_cnpj = request.form['cpf_cnpj']
        telefone = request.form['telefone']
        endereco = request.form.get('endereco')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')
        cep = request.form.get('cep')

        # Verifica se o email já existe
        if Admin.query.filter_by(email=email).first() or Cliente.query.filter_by(email=email).first():
            flash('E-mail já cadastrado. Use outro ou faça login.', 'warning')
            return redirect(url_for('routes.cadastro'))

        cliente = Cliente(
            nome=nome,
            email=email,
            senha=senha,
            cpf_cnpj=cpf_cnpj,
            telefone=telefone,
            endereco=endereco,
            cidade=cidade,
            estado=estado,
            cep=cep
        )
        db.session.add(cliente)
        db.session.commit()
        flash('Cadastro realizado! Faça login.', 'success')

        # ✅ Redireciona para a tela de login com o modal aberto
        return redirect(url_for('routes.index') + '?modal=login_cliente')

    return render_template('cadastro.html')

from app.models import Produto, Categoria

@routes.route('/')
def index():
    from app.models import Produto, Colecao
    banners = Banner.query.filter_by(ativo=True).order_by(Banner.ordem).all()
    ano_atual = datetime.now().year
    slug_ano_atual = f"colecao-{ano_atual}"

    # Busca a coleção do ano atual
    colecao_ano = Colecao.query.filter_by(slug=slug_ano_atual, ativa=True).first()
    produtos_colecao_ano = colecao_ano.produtos if colecao_ano else []

    # Demais coleções ativas, ordenadas pelo slug (ano decrescente)
    outras_colecoes = (
        Colecao.query
        .filter(Colecao.ativa == True, Colecao.slug != slug_ano_atual)
        .order_by(Colecao.slug.desc())
        .all()
    )

    # Produtos em destaque
    produtos_destaque = Produto.query.filter_by(destaque=True, ativo=True).all()

    # Carrinho e subtotal
    carrinho = session.get('carrinho', [])
    subtotal = sum(item['preco_total'] for item in carrinho)

    return render_template(
        'index.html',
        produtos_colecao_ano=produtos_colecao_ano,
        colecao_ano=colecao_ano,
        outras_colecoes=outras_colecoes,
        produtos_destaque=produtos_destaque,
        carrinho=carrinho,
        subtotal=subtotal,
        banners=banners,
    )


from app.models import Produto, Colecao

# --- Rotas admin colecoes ---
@routes.route('/admin/colecoes')
@login_required
def admin_colecoes():
    if not isinstance(current_user, Admin):
        abort(403)
    colecoes = Colecao.query.order_by(Colecao.id.desc()).all()
    return render_template('admin/colecoes.html', colecoes=colecoes)

@routes.route('/admin/colecoes/adicionar', methods=['POST'])
@login_required
def adicionar_colecao():
    if not isinstance(current_user, Admin):
        abort(403)
    nome = request.form.get('nome')
    slug = request.form.get('slug')
    descricao = request.form.get('descricao')
    ativa = True if request.form.get('ativa') == 'on' else False

    imagem = request.files.get('imagem')
    imagem_nome = None
    if imagem and imagem.filename:
        imagem_nome = secure_filename(imagem.filename)
        caminho = os.path.join(current_app.static_folder, 'images', imagem_nome)
        imagem.save(caminho)

    colecao = Colecao(nome=nome, slug=slug, descricao=descricao, ativa=ativa, imagem=imagem_nome)
    db.session.add(colecao)
    db.session.commit()
    flash('Coleção adicionada com sucesso!', 'success')
    return redirect(url_for('routes.admin_colecoes'))

@routes.route('/admin/colecoes/<int:colecao_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_colecao(colecao_id):
    if not isinstance(current_user, Admin):
        abort(403)
    colecao = Colecao.query.get_or_404(colecao_id)
    if request.method == 'POST':
        colecao.nome = request.form.get('nome')
        colecao.slug = request.form.get('slug')
        colecao.descricao = request.form.get('descricao')
        colecao.ativa = True if request.form.get('ativa') == 'on' else False

        imagem = request.files.get('imagem')
        if imagem and imagem.filename:
            filename = secure_filename(imagem.filename)
            caminho = os.path.join(current_app.static_folder, 'images', filename)
            imagem.save(caminho)
            colecao.imagem = filename

        db.session.commit()
        flash("Coleção atualizada com sucesso!", "success")
        return redirect(url_for('routes.admin_colecoes'))
    return render_template('editar_colecao.html', colecao=colecao)

@routes.route('/admin/colecoes/<int:colecao_id>/excluir', methods=['POST'])
@login_required
def excluir_colecao(colecao_id):
    if not isinstance(current_user, Admin):
        abort(403)
    colecao = Colecao.query.get_or_404(colecao_id)
    db.session.delete(colecao)
    db.session.commit()
    flash('Coleção excluída com sucesso!', 'info')
    return redirect(url_for('routes.admin_colecoes'))

# --- Rotas admin banners ---
@routes.route('/admin/banners')
@login_required
def admin_banners():
    if not isinstance(current_user, Admin):
        abort(403)
    banners = Banner.query.order_by(Banner.ordem).all()
    return render_template('admin/admin_banners.html', banners=banners)

@routes.route('/admin/banners/add', methods=['POST'])
def add_banner():
    titulo = request.form.get('titulo')
    ordem = request.form.get('ordem')
    ativo = bool(int(request.form.get('ativo', 1)))

    file = request.files.get('imagem')
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        # Caminho absoluto até a pasta /static/banners
        banner_folder = os.path.join(current_app.root_path, 'static', 'banners')
        os.makedirs(banner_folder, exist_ok=True)  # Cria a pasta se não existir

        # Caminho final do arquivo
        file_path = os.path.join(banner_folder, filename)
        file.save(file_path)
    else:
        flash('Imagem obrigatória', 'danger')
        return redirect(url_for('routes.admin_banners'))

    # Aqui, você salva os dados no banco, exemplo:
    novo_banner = Banner(
        titulo=titulo,
        ordem=ordem,
        ativo=ativo,
        imagem=filename  # Só o nome do arquivo!
    )
    db.session.add(novo_banner)
    db.session.commit()

    flash('Banner adicionado com sucesso!', 'success')
    return redirect(url_for('routes.admin_banners'))

@routes.route('/admin/banners/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_banner(id):
    if not isinstance(current_user, Admin):
        abort(403)
    banner = Banner.query.get_or_404(id)
    banner.titulo = request.form['titulo']
    banner.subtitulo = request.form.get('subtitulo')
    banner.link_botao = request.form.get('link_botao')
    banner.texto_botao = request.form.get('texto_botao')
    banner.ordem = request.form.get('ordem', type=int, default=1)
    banner.ativo = bool(request.form.get('ativo'))

    imagem_file = request.files.get('imagem')
    if imagem_file and imagem_file.filename:
        filename = secure_filename(imagem_file.filename)
        caminho = os.path.join(current_app.static_folder, 'uploads/banners', filename)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        imagem_file.save(caminho)
        banner.imagem = f'uploads/banners/{filename}'

    db.session.commit()
    flash('Banner atualizado com sucesso.')
    return redirect(url_for('routes.admin_banners'))

@routes.route('/admin/banners/delete/<int:id>', methods=['POST', 'GET'])
@login_required
def delete_banner(id):
    if not isinstance(current_user, Admin):
        abort(403)
    banner = Banner.query.get_or_404(id)
    db.session.delete(banner)
    db.session.commit()
    flash('Banner excluído com sucesso.')
    return redirect(url_for('routes.admin_banners'))

# PRODUTOS
@routes.route('/produtos')
def produtos():
    categoria = request.args.get('categoria')
    categorias = Categoria.query.all()
    if categoria and categoria != 'todas':
        produtos = Produto.query.join(Categoria).filter(Categoria.nome == categoria, Produto.ativo == True).all()
    else:
        produtos = Produto.query.filter_by(ativo=True).order_by(Produto.id.desc()).all()
    return render_template('produtos.html', produtos=produtos, categorias=categorias, categoria=categoria)


@routes.route('/produto/<int:produto_id>')
def produto_detail(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    fotos_extras = ProdutoImagem.query.filter_by(produto_id=produto.id).all()

    # Garante que seja um dicionário, mesmo se vier como string JSON
    if isinstance(produto.cores_imagens, str):
        import json
        try:
            cores = json.loads(produto.cores_imagens)
        except Exception:
            cores = {}
    else:
        cores = produto.cores_imagens or {}


    return render_template(
        'produto_detail.html',
        produto=produto,
        fotos_extras=fotos_extras,
        cores=cores
    )


# CARRINHO
def inicializa_carrinho():
    if 'carrinho' not in session:
        session['carrinho'] = []

@routes.route('/adicionar_ao_carrinho/<int:produto_id>', methods=['POST'])
def adicionar_ao_carrinho(produto_id):
    inicializa_carrinho()
    cor = request.form.get('cor')
    qtd_caixas = int(request.form.get('qtd', 1))
    produto = Produto.query.get_or_404(produto_id)

    pares_por_caixa = produto.qtd_minima or 12
    total_pares = qtd_caixas * pares_por_caixa
    preco_unitario = produto.preco_par or 0.0
    preco_parcelado = produto.preco_parcelado or round(preco_unitario * 1.08, 2)
    preco_total = total_pares * preco_unitario

    item = {
        'produto_id': produto.id,
        'nome_produto': produto.nome,
        'cor': cor,
        'quantidade': qtd_caixas,
        'pares_por_caixa': pares_por_caixa,
        'preco_unitario': preco_unitario,
        'preco_parcelado': preco_parcelado,
        'preco_total': preco_total,
        'imagem_produto': produto.imagem_principal
    }

    session['carrinho'].append(item)
    session.modified = True

    # 👉 Retorna JSON para fetch (sem redirecionar)
    unidade = "caixa" if qtd_caixas == 1 else "caixas"
    return jsonify({"status": "ok",
                    "mensagem": f'{qtd_caixas} {unidade} de "{produto.nome}" adicionada{"s" if qtd_caixas > 1 else ""} ao carrinho.'})


@routes.route('/carrinho')
def carrinho():
    carrinho = session.get('carrinho', [])
    subtotal = sum(item['preco_total'] for item in carrinho)
    return render_template('carrinho.html', carrinho=carrinho, subtotal=subtotal)

@routes.route('/carrinho/limpar')
def limpar_carrinho():
    session.pop('carrinho', None)
    flash('Carrinho limpo com sucesso!', 'info')
    return redirect(url_for('routes.carrinho'))


@routes.route('/carrinho/limpar_selecionados', methods=['POST'])
def limpar_selecionados():
    selecionados = request.form.getlist('selecionados')
    carrinho = session.get('carrinho', [])
    carrinho = [item for i, item in enumerate(carrinho) if str(i) not in selecionados]
    session['carrinho'] = carrinho
    session.modified = True
    return redirect(url_for('routes.carrinho'))

@routes.route('/carrinho/limpar_tudo', methods=['POST'])
def limpar_tudo():
    session.pop('carrinho', None)
    return jsonify({'status': 'ok', 'mensagem': 'Carrinho limpo.'})


@routes.route('/remover_do_carrinho/<int:index>', methods=['POST'])
def remover_do_carrinho(index):
    carrinho = session.get('carrinho', [])
    if 0 <= index < len(carrinho):
        del carrinho[index]
        session.modified = True
    return redirect(url_for('routes.carrinho'))




# CHECKOUT
@routes.route('/checkout', methods=['POST'])
@login_required
def checkout():
    metodo = request.form.get("metodo_pagamento")
    pedido_id = session.get("pedido_id")  # ou adapte conforme seu controle de pedido

    if not pedido_id:
        flash("Pedido não encontrado.")
        return redirect(url_for('routes.carrinho'))

    if metodo == "pix":
        return redirect(url_for('routes.pagamento_pix', pedido_id=pedido_id))
    elif metodo == "pagseguro":
        return redirect(url_for('routes.pagamento_pagseguro', pedido_id=pedido_id))
    else:
        flash("Método de pagamento inválido.")
        return redirect(url_for('routes.checkout'))

@routes.route('/finalizar_pedido', methods=['POST'])
@login_required
def finalizar_pedido():
    metodo = request.form.get("metodo_pagamento")
    carrinho = session.get("carrinho", [])

    if not carrinho:
        flash("Seu carrinho está vazio.")
        return redirect(url_for('routes.carrinho'))

    try:
        frete_valor = float(session.get('frete_valor') or 0.0)
    except (ValueError, TypeError):
        frete_valor = 0.0

    try:
        total_itens = sum(float(item['preco_total']) for item in carrinho)
    except (KeyError, TypeError, ValueError):
        flash("Erro ao calcular o valor total do pedido.")
        return redirect(url_for('routes.carrinho'))

    total = total_itens + frete_valor

    if total is None or not isinstance(total, (int, float)):
        current_app.logger.warning("[ERRO] Total do pedido é inválido ou None.")
        flash("Erro ao finalizar o pedido. Tente novamente.")
        return redirect(url_for('routes.carrinho'))

    novo_pedido = Pedido(
        cliente_id=current_user.id,
        data=datetime.now(fuso_brasil),
        frete_valor=frete_valor,
        frete_transportadora=session.get('frete_transportadora'),
        frete_prazo=session.get('frete_prazo'),
        total=total
    )
    db.session.add(novo_pedido)
    db.session.flush()

    for item in carrinho:
        novo_item = ItemPedido(
            pedido_id=novo_pedido.id,
            produto_id=item['produto_id'],
            nome_produto=item['nome_produto'],
            cor=item.get('cor'),
            quantidade=item['quantidade'],
            preco_unitario=item['preco_unitario'],
            preco_total=item['preco_total'],
            tamanho=item.get('tamanho'),
            imagem_produto=item.get('imagem_produto')
        )
        db.session.add(novo_item)

    db.session.commit()
    session['pedido_id'] = novo_pedido.id
    session.pop('carrinho', None)

    if metodo == "pix":
        return redirect(url_for('routes.pagamento_pix', pedido_id=novo_pedido.id))
    elif metodo == "pagseguro":
        return redirect(url_for('routes.pagamento_pagseguro', pedido_id=novo_pedido.id))
    elif metodo == "mercadopago":
        return redirect(url_for('routes.pagamento_mercadopago', pedido_id=novo_pedido.id))
    else:
        flash("Método de pagamento inválido.")
        return redirect(url_for('routes.carrinho'))






@routes.route('/meus_pedidos')
@login_required
def pedidos_cliente():
    pedidos = Pedido.query.filter_by(cliente_id=current_user.id).order_by(Pedido.data.desc()).all()
    return render_template('pedidos_cliente.html', pedidos=pedidos)

@routes.route('/pedido/<int:pedido_id>')
@login_required
def pedido_detalhe(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    if pedido.cliente_id != current_user.id and not isinstance(current_user, Admin):
        abort(403)
    return render_template('pedido_detalhe.html', pedido=pedido)

# ÁREA DO CLIENTE
@routes.route('/area_cliente')
@login_required
def area_cliente():
    if not isinstance(current_user, Cliente):
        abort(403)

    pedidos = Pedido.query.filter_by(cliente_id=current_user.id).order_by(Pedido.data.desc()).all()
    return render_template('area_cliente.html', cliente=current_user, pedidos=pedidos)


# ─── ADMIN – DASHBOARD ─────────────────────────────────────────────────────────

@routes.route('/admin')
@login_required
def painel_admin():
    if not isinstance(current_user, Admin):
        flash("Acesso restrito à administração.", "danger")
        return redirect(url_for('routes.index'))
    ...
    total_clientes = Cliente.query.count()
    total_pedidos  = Pedido.query.count()
    produtos       = Produto.query.order_by(Produto.id.desc()).all()
    categorias = Categoria.query.order_by(Categoria.nome).all()
    colecoes_ativas = Colecao.query.filter_by(ativa=True).all()
    banners = Banner.query.all()
    fotos_extras_dict = {
        p.id: ProdutoImagem.query.filter_by(produto_id=p.id).all() for p in produtos
    }

    return render_template(
        'admin_dashboard.html',
        produtos=produtos,
        total_clientes=total_clientes,
        total_pedidos=total_pedidos,
        categorias=categorias,
        fotos_extras_dict=fotos_extras_dict,
        colecoes_ativas=colecoes_ativas,
        banners=banners,
    )

# ─── ADMIN – PEDIDOS ──────────────────────────────────────────────────────────

def filtrar_pedidos(pedidos, data_inicio=None, data_fim=None, status=None, cliente=None):
    if data_inicio:
        data_inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
        pedidos = [p for p in pedidos if p.data >= data_inicio]
    if data_fim:
        data_fim = datetime.strptime(data_fim, "%Y-%m-%d")
        pedidos = [p for p in pedidos if p.data <= data_fim]
    if status:
        pedidos = [p for p in pedidos if p.status == status]
    if cliente:
        cliente = cliente.lower()
        pedidos = [p for p in pedidos if (p.cliente and (
            cliente in p.cliente.nome.lower() or cliente in p.cliente.email.lower()))]
    return pedidos

@routes.route('/admin/pedidos')
@login_required
def admin_pedidos():
    if not isinstance(current_user, Admin):
        abort(403)

    pedidos = Pedido.query.order_by(Pedido.data.desc()).all()
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    status = request.args.get('status')
    cliente = request.args.get('cliente')

    from sqlalchemy.orm import joinedload
    pedidos = Pedido.query.options(joinedload(Pedido.cliente)).order_by(Pedido.data.desc()).all()
    return render_template('admin_pedidos.html', pedidos=pedidos)


@routes.route('/admin/pedido/<int:pedido_id>', methods=['GET', 'POST'])
@login_required
def admin_pedido_detalhe(pedido_id):
    if not isinstance(current_user, Admin):
        abort(403)
    pedido = Pedido.query.get_or_404(pedido_id)

    if request.method == 'POST':
        novo_status = request.form.get('novo_status')
        if novo_status in ['Aguardando pagamento','Pago','Em produção','Pronto para envio','Enviado','Cancelado']:
            pedido.status = novo_status
            db.session.commit()
            flash('Status atualizado!', 'success')
        return redirect(url_for('routes.admin_pedido_detalhe', pedido_id=pedido.id))

    return render_template('admin_pedido_detalhe.html', pedido=pedido)

# ─── ADMIN – CLIENTES ─────────────────────────────────────────────────────────

@routes.route('/admin/clientes')
@login_required
def admin_clientes():
    if not isinstance(current_user, Admin):
        abort(403)
    clientes = Cliente.query.order_by(Cliente.id.desc()).all()
    return render_template('admin_clientes.html', clientes=clientes)

@routes.route('/admin/cliente/<int:cliente_id>/pedidos')
@login_required
def admin_cliente_pedidos(cliente_id):
    if not isinstance(current_user, Admin):
        abort(403)
    cliente = Cliente.query.get_or_404(cliente_id)
    # traz todos os pedidos desse cliente
    pedidos = Pedido.query.filter_by(cliente_id=cliente.id).order_by(Pedido.data.desc()).all()
    return render_template('admin_cliente_detalhe.html',
                           cliente=cliente,
                           pedidos=pedidos)

# ─── ADMIN – CATEGORIAS ────────────────────────────────────────────────────────

@routes.route('/admin/categorias')
@login_required
def admin_categorias():
    if not isinstance(current_user, Admin):
        abort(403)
    categorias = Categoria.query.order_by(Categoria.nome).all()
    return render_template('admin_categorias.html', categorias=categorias)

@routes.route('/admin/categorias', methods=['POST'])
@login_required
def adicionar_categoria():
    if not isinstance(current_user, Admin):
        abort(403)
    nome = request.form.get('nome_categoria')
    if nome:
        cat = Categoria(nome=nome)
        db.session.add(cat)
        db.session.commit()
        flash('Categoria adicionada!', 'success')
    return redirect(url_for('routes.admin_categorias'))

@routes.route('/admin/categorias/<int:categoria_id>/editar', methods=['POST'])
@login_required
def editar_categoria(categoria_id):
    if not isinstance(current_user, Admin):
        abort(403)
    nova = request.form.get('novo_nome')
    categoria = Categoria.query.get_or_404(categoria_id)
    if nova:
        categoria.nome = nova
        db.session.commit()
        flash('Categoria atualizada!', 'success')
    return redirect(url_for('routes.admin_categorias'))

@routes.route('/admin/categorias/<int:categoria_id>/excluir', methods=['POST'])
@login_required
def excluir_categoria(categoria_id):
    if not isinstance(current_user, Admin):
        abort(403)
    categoria = Categoria.query.get_or_404(categoria_id)
    db.session.delete(categoria)
    db.session.commit()
    flash('Categoria excluída!', 'info')
    return redirect(url_for('routes.admin_categorias'))

@routes.route('/admin/adicionar_produto', methods=['POST'])
@login_required
def adicionar_produto():
    # só Admin pode
    if not isinstance(current_user, Admin):
        abort(403)

    # campos do formulário
    codigo = request.form.get('codigo')
    nome            = request.form.get('nome')
    descricao       = request.form.get('descricao')
    descricao_curta = request.form.get('descricao_detalhada') or ''
    preco_caixa     = float(request.form.get('preco_caixa', 0))
    preco_par       = float(request.form.get('preco_par', 0))
    qtd_minima      = int(request.form.get('qtd_minima', 1))
    categoria_id    = int(request.form.get('categoria_id'))
    # Recebe tamanhos e estoques separados por vírgula
    grade_keys = request.form.get('grade_keys', '').split(',')
    grade_values = request.form.get('grade_values', '').split(',')
    colecao_id = request.form.get('colecao_id') or None

    # Monta o dicionário grade = { tamanho: estoque }
    grade = {}
    if len(grade_keys) == len(grade_values):
        for k, v in zip(grade_keys, grade_values):
            grade[k.strip()] = int(v.strip())

    # *1) SALVAR IMAGEM PRINCIPAL*
    imagem_principal = None
    arquivo = request.files.get('foto')
    if arquivo and arquivo.filename:
        fn = secure_filename(arquivo.filename)
        upload_path = os.path.join(current_app.root_path, 'static', 'images', fn)
        arquivo.save(upload_path)
        imagem_principal = fn

    preco_par = float(request.form.get('preco_par', 0))
    preco_parcelado = int(request.form.get('preco_parcelado'))
    preco_caixa = round(preco_par * 12)
    tipo_salto = request.form.get('tipo_salto')

    cores_imagens = {}
    nomes_cores = request.form.getlist('cores_nomes[]')
    imagens_cores = request.files.getlist('cores_imagens[]')
    for cor, imagem in zip(nomes_cores, imagens_cores):
        if imagem and imagem.filename:
            filename = secure_filename(imagem.filename)
            caminho = os.path.join(current_app.static_folder, 'images', filename)
            imagem.save(caminho)
            cores_imagens[cor.strip()] = filename



    produto = Produto(
        codigo=codigo,
        nome=nome,
        descricao=descricao,
        descricao_curta=descricao_curta,
        preco_caixa=preco_caixa,
        preco_par=preco_par,
        preco_parcelado=preco_parcelado,
        cores_imagens=cores_imagens,
        qtd_minima=qtd_minima,
        categoria_id=categoria_id,
        grade=grade,
        imagem_principal=imagem_principal,
        tipo_salto=tipo_salto,
    )
    produto.colecao_id = request.form.get('colecao_id') or None

    db.session.add(produto)
    db.session.flush()  # para ter produto.id antes do commit

    # *2) SALVAR FOTOS EXTRAS*
    extras = request.files.getlist('fotos')
    for img in extras:
        if img and img.filename:
            # Evita sobrescrever e garante nome único com timestamp
            filename = secure_filename(img.filename)
            filepath = os.path.join(current_app.root_path, 'static', 'images', filename)

            # Garante que a pasta exista
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            img.save(filepath)

            # Salva no banco
            nova_imagem = ProdutoImagem(produto_id=produto.id, imagem=filename)
            db.session.add(nova_imagem)

    produto.cores_imagens = cores_imagens  # já é JSON nativo (dict), pode salvar direto
    print("Cores recebidas:", cores_imagens)

    db.session.commit()
    flash(f'Produto "{produto.nome}" cadastrado com sucesso!', 'success')
    return redirect(url_for('routes.painel_admin'))

@routes.route('/admin/editar_produto/<int:produto_id>', methods=['POST'])
@login_required
def editar_produto(produto_id):
    if not isinstance(current_user, Admin):
        abort(403)

    produto = Produto.query.get_or_404(produto_id)

    produto.codigo = request.form['codigo']
    produto.nome = request.form['nome']
    produto.descricao_curta = request.form.get('descricao_curta')
    produto.descricao = request.form.get('descricao')

    produto.preco_par = float(request.form['preco_par'].replace(',', '.'))
    produto.preco_parcelado = float(request.form['preco_parcelado'].replace(',', '.'))
    produto.qtd_minima = int(float(request.form['qtd_minima'].replace(',', '.')))
    produto.preco_caixa = round(produto.preco_par * produto.qtd_minima)

    produto.categoria_id = int(request.form['categoria_id'])
    produto.tipo_salto = request.form.get('tipo_salto')

    # 🆕 Coleção: converte para int ou None
    colecao_id = request.form.get('colecao_id')
    produto.colecao_id = int(colecao_id) if colecao_id else None

    # 🟨 Cores com imagens
    nomes_cores = request.form.getlist('cores_nomes[]')
    imagens_cores = request.files.getlist('cores_imagens[]')
    novas_cores = {}

    for i, nome in enumerate(nomes_cores):
        nome = nome.strip()
        imagem = imagens_cores[i] if i < len(imagens_cores) else None

        if imagem and imagem.filename:
            filename = secure_filename(imagem.filename)
            caminho = os.path.join(current_app.static_folder, 'images', filename)
            imagem.save(caminho)
            novas_cores[nome] = filename
        else:
            if produto.cores_imagens and nome in produto.cores_imagens:
                novas_cores[nome] = produto.cores_imagens[nome]

    produto.cores_imagens = novas_cores

    # 📷 Foto principal
    foto = request.files.get('foto')
    if foto and foto.filename:
        filename = secure_filename(foto.filename)
        foto.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        produto.imagem_principal = filename

    # 📸 Fotos extras
    extras = request.files.getlist('fotos')
    for f in extras:
        if f and f.filename:
            fn = secure_filename(f.filename)
            caminho = os.path.join(current_app.root_path, 'static', 'images', fn)
            existe = ProdutoImagem.query.filter_by(produto_id=produto.id, imagem=fn).first()
            if not existe:
                f.save(caminho)
                nova = ProdutoImagem(produto_id=produto.id, imagem=fn)
                db.session.add(nova)

    db.session.commit()
    flash('Produto atualizado com sucesso!', 'success')
    return redirect(url_for('routes.painel_admin'))


@routes.route('/admin/produto/destaque/<int:produto_id>', methods=['POST'])
@login_required
def marcar_destaque(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    produto.destaque = not produto.destaque
    db.session.commit()
    return jsonify({'status': 'ok', 'destaque': produto.destaque})

# ROTAS COLEÇÃO  --------------------------
@routes.route('/admin/colecao/toggle/<int:produto_id>', methods=['POST'])
@login_required
def toggle_colecao(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    # 1) Se for manter o booleano:
    # produto.colecao_2025 = not produto.colecao_2025

    # 2) PARA COLEÇÕES DINÂMICAS:
    # receba o ID da coleção via form ou query string
    colecao_id = request.args.get('colecao_id', type=int)
    if not colecao_id:
        abort(400)
    colecao = Colecao.query.get_or_404(colecao_id)

    if colecao in produto.colecoes:
        produto.colecoes.remove(colecao)
    else:
        produto.colecoes.append(colecao)

    db.session.commit()
    return ('', 204)


@routes.route('/admin/produto/<int:produto_id>/colecoes')
def get_colecoes_do_produto(produto_id):
    produto = Produto.query.get(produto_id)
    if produto:
        colecoes_ids = [colecao.id for colecao in produto.colecoes]
        return jsonify({'colecoes_ids': colecoes_ids})
    return jsonify({'colecoes_ids': []}), 404



@routes.route('/admin/produto/<int:produto_id>/toggle_destaque', methods=['POST'])
@login_required
def toggle_destaque(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    produto.destaque = not produto.destaque
    db.session.commit()
    return jsonify({'destaque': produto.destaque})

@routes.route('/admin/produto/<int:produto_id>/toggle', methods=['POST'])
@login_required
def toggle_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    produto.ativo = not produto.ativo
    db.session.commit()
    status = "ativado" if produto.ativo else "desativado"
    flash(f'Produto {status} com sucesso!', 'success')
    return redirect(request.referrer or url_for('routes.ainel_admin'))



@routes.route('/admin/excluir_produto/<int:produto_id>', methods=['POST'])
@login_required
def excluir_produto(produto_id):
    if not isinstance(current_user, Admin):
        abort(403)

    produto = Produto.query.get_or_404(produto_id)

    # 1. Deletar imagens associadas
    imagens = ProdutoImagem.query.filter_by(produto_id=produto.id).all()
    for img in imagens:
        db.session.delete(img)

    # 2. Deletar o produto
    db.session.delete(produto)
    db.session.commit()

    flash(f'Produto "{produto.nome}" excluído com sucesso.', 'success')
    return redirect(url_for('routes.painel_admin'))

@routes.route('/admin/produto/<int:produto_id>/excluir_imagem/<int:imagem_id>', methods=['POST'])
@login_required
def excluir_imagem_extra(produto_id, imagem_id):
    if not isinstance(current_user, Admin):
        abort(403)

    imagem = ProdutoImagem.query.get_or_404(imagem_id)

    # Remove do banco
    db.session.delete(imagem)

    # Remove do disco
    caminho = os.path.join(current_app.root_path, 'static', 'images', imagem.imagem)
    if os.path.exists(caminho):
        os.remove(caminho)

    db.session.commit()
    flash('Imagem removida com sucesso.', 'info')
    return redirect(url_for('routes.painel_admin'))

@routes.route('/admin/produto/<int:produto_id>/imagens_extras')
@login_required
def imagens_extras(produto_id):
    if not isinstance(current_user, Admin):
        abort(403)
    imagens = ProdutoImagem.query.filter_by(produto_id=produto_id).all()
    return jsonify([{
        'id': img.id,
        'url': url_for('static', filename='images/' + img.imagem)
    } for img in imagens])

@routes.route('/admin/pedido/<int:pedido_id>/confirmar_pagamento', methods=['POST'])
@login_required
def confirmar_pagamento(pedido_id):
    if not isinstance(current_user, Admin):
        abort(403)
    pedido = Pedido.query.get_or_404(pedido_id)
    pedido.status = 'Pago'
    db.session.commit()
    flash('Pagamento confirmado com sucesso.', 'success')
    return redirect(url_for('routes.admin_pedido_detalhe', pedido_id=pedido.id))

@routes.route('/admin/pedido/<int:pedido_id>/atualizar_status', methods=['POST'])
@login_required
def atualizar_status_pedido(pedido_id):
    if not isinstance(current_user, Admin):
        abort(403)

    pedido = Pedido.query.get_or_404(pedido_id)
    novo_status = request.form.get('novo_status')

    if novo_status in ['Aguardando pagamento', 'Pago', 'Em produção', 'Pronto para envio', 'Enviado', 'Cancelado']:
        pedido.status = novo_status
        db.session.commit()
        flash('Status do pedido atualizado com sucesso!', 'success')

    return redirect(url_for('routes.admin_pedido_detalhe', pedido_id=pedido.id))


@routes.route('/admin/pedido/<int:pedido_id>/emitir_nf', methods=['POST'])
@login_required
def emitir_nf(pedido_id):
    if not isinstance(current_user, Admin):
        abort(403)

    pedido = Pedido.query.get_or_404(pedido_id)

    # Simulação da emissão da NF
    pedido.nf_emitida = True
    pedido.numero_nf = f"NF{pedido.id:06d}"

    db.session.commit()
    flash("Nota fiscal emitida com sucesso!", "success")
    return redirect(url_for('routes.admin_pedido_detalhe', pedido_id=pedido.id))


from fpdf import FPDF
from flask import send_file
from io import BytesIO
import os


@routes.route('/admin/pedido/<int:pedido_id>/pdf')
@login_required
def baixar_pedido_pdf(pedido_id):
    if not isinstance(current_user, Admin):
        abort(403)

    pedido = Pedido.query.get_or_404(pedido_id)
    cliente = pedido.cliente

    pdf = FPDF()
    pdf.add_page()

    # Fontes UTF-8
    font_dir = os.path.join(current_app.root_path, "static", "fonts")
    pdf.add_font("DejaVu", "", os.path.join(font_dir, "DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu", "B", os.path.join(font_dir, "DejaVuSans-Bold.ttf"), uni=True)
    pdf.set_font("DejaVu", "", 12)

    # Logo
    logo_path = os.path.join(current_app.root_path, "static", "images", "logo.png")
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=40)
    pdf.ln(25)

    # Cabeçalho do pedido
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(0, 10, f"Pedido #{pedido.id}", ln=True)

    pdf.set_font("DejaVu", "", 11)
    pdf.cell(0, 8, f"Cliente: {cliente.nome if cliente else 'Cliente não encontrado'}", ln=True)
    pdf.cell(0, 8, f"Cidade: {cliente.cidade if cliente else '-'} / {cliente.estado if cliente else '-'}", ln=True)
    pdf.cell(0, 8, f"Data do Pedido: {pedido.data.strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.cell(0, 8, f"Status: {pedido.status}", ln=True)

    if pedido.frete_transportadora:
        pdf.cell(0, 8, f"Frete: {pedido.frete_transportadora} – R$ {pedido.frete_valor:.2f} ({pedido.frete_prazo})",
                 ln=True)

    pdf.ln(6)

    for item in pedido.itens:
        produto = Produto.query.get(item.produto_id)
        if not produto:
            continue

        pdf.set_font("DejaVu", "B", 12)
        pdf.cell(0, 10, f"{produto.nome}", ln=True)
        pdf.set_font("DejaVu", "", 11)

        # Imagem principal
        if produto.imagem_principal:
            img_path = os.path.join(current_app.root_path, "static", "images", produto.imagem_principal)
            if os.path.exists(img_path):
                pdf.image(img_path, x=pdf.get_x(), y=pdf.get_y(), w=40)
                pdf.ln(45)
            else:
                pdf.ln(5)

        # Código e cor do produto
        pdf.cell(0, 8, f"Cód: {getattr(produto, 'codigo', '---')}", ln=True)

        if hasattr(item, 'cor') and item.cor:
            pdf.cell(0, 8, f"Cor: {item.cor}", ln=True)

        pdf.cell(0, 8, f"Qtd: {item.quantidade} caixas ({item.quantidade * produto.qtd_minima} pares)", ln=True)

        # Grade (tamanhos e quantidades)
        grade = produto.grade or {}
        if grade:
            tamanhos = list(grade.keys())
            quantidades = [str(grade[t]) for t in tamanhos]

            pdf.set_font("DejaVu", "B", 10)
            for t in tamanhos:
                pdf.cell(15, 8, str(t), border=1, align='C')
            pdf.ln()
            pdf.set_font("DejaVu", "", 10)
            for q in quantidades:
                pdf.cell(15, 8, str(q), border=1, align='C')
            pdf.ln(12)

        # Observações (se quiser deixar dinâmico depois)
        observacao = "Sem observações"
        pdf.multi_cell(0, 8, f"Observações: {observacao}")
        pdf.ln(6)

        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    # Rodapé
    pdf.ln(8)
    pdf.set_font("DejaVu", "", 11)
    pdf.cell(0, 10, "✔️ Revisado por: _____________________________   Data: ___/___/____", ln=True)

    # Exporta como arquivo PDF
    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f"pedido_{pedido.id}.pdf", mimetype='application/pdf')


@routes.route('/simular_frete', methods=['POST'])
def simular_frete():
    cep = request.form.get('cep')
    carrinho = session.get('carrinho', [])

    if not cep:
        flash("Digite um CEP válido.", "warning")
        return redirect(url_for('routes.carrinho'))

    peso_total = 0
    for item in carrinho:
        produto = Produto.query.get(item['produto_id'])
        if produto:
            peso_total += produto.peso * item['quantidade']

    opcoes = listar_opcoes_frete(cep, peso_total)
    endereco = consultar_endereco(cep)

    if not opcoes:
        flash("Não foi possível calcular o frete para esse CEP.", "warning")
        return redirect(url_for('routes.carrinho'))

    session['cep_cliente'] = cep
    session['endereco_cliente'] = endereco or "Endereço não encontrado"
    session['frete_opcoes'] = opcoes
    session.pop('frete_valor', None)
    session.pop('frete_transportadora', None)
    session.pop('frete_prazo', None)

    return redirect(url_for('routes.carrinho'))



@routes.route('/selecionar_frete', methods=['POST'])
def selecionar_frete():
    try:
        index = int(request.form.get('frete_escolhido'))
        opcoes = session.get('frete_opcoes', [])

        if 0 <= index < len(opcoes):
            opcao = opcoes[index]
            session['frete_valor'] = opcao['valor']
            session['frete_transportadora'] = opcao['transportadora']
            session['frete_prazo'] = opcao['prazo']
            session['frete_escolhido'] = index  # marca que foi escolhido
            flash(f"Frete selecionado: {opcao['transportadora']} - R$ {opcao['valor']}", "success")
        else:
            flash("Erro ao selecionar frete.", "danger")

    except Exception:
        flash("Erro ao processar a escolha do frete.", "danger")

    return redirect(url_for('routes.carrinho'))


@routes.route('/pagamento/sucesso')
@login_required
def pagamento_sucesso():
    pedido_id = session.get("pedido_id")

    # Se não houver na sessão, tenta recuperar via external_reference do Mercado Pago
    if not pedido_id:
        external_reference = request.args.get("external_reference")
        if external_reference and external_reference.isdigit():
            pedido_id = int(external_reference)

    if not pedido_id:
        flash("Pedido não encontrado.")
        return redirect(url_for('routes.index'))

    pedido = Pedido.query.get(pedido_id)
    if not pedido:
        flash("Pedido não encontrado no banco de dados.")
        return redirect(url_for('routes.index'))

    # Atualiza o status do pedido apenas se necessário
    if pedido.status == "Aguardando pagamento":
        pedido.status = "Pago via Mercado Pago"
        db.session.commit()

        # Envia e-mail somente se houver cliente e e-mail
        if pedido.cliente and pedido.cliente.email:
            try:
                from app.utils.email import enviar_email_confirmacao
                enviar_email_confirmacao(pedido.cliente.email, pedido)
            except Exception as e:
                current_app.logger.warning(f"Erro ao enviar e-mail: {e}")

    # Sempre limpa a sessão (evita duplicação)
    session.pop("pedido_id", None)
    session.pop("carrinho", None)

    return render_template('pedido_confirmado.html', pedido=pedido)






@routes.route('/como-comprar')
def como_comprar():
    return render_template('como_comprar.html')

@routes.route('/prazo-entrega')
def prazo_entrega():
    return render_template('prazo_entrega.html')

@routes.route('/trocas-devolucao')
def trocas_devolucao():
    return render_template('trocas_devolucao.html')

@routes.route('/entregas-retirada')
def entregas_retirada():
    return render_template('entregas_retirada.html')

@routes.route('/quem-somos')
def quem_somos():
    return render_template('quem_somos.html')

@routes.route('/formas-pagamento')
def formas_pagamento():
    return render_template('formas_pagamento.html')

@routes.route('/destaques')
def destaques():
    return render_template('destaques.html')

