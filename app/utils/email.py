from flask_mail import Message
from flask import render_template, current_app
from app import mail

def enviar_email_confirmacao(destinatario, pedido):
    try:
        # Proteção dos campos principais
        pedido_id = getattr(pedido, "id", "N/A")
        total = float(getattr(pedido, "total", 0.0) or 0.0)
        frete_valor = float(getattr(pedido, "frete_valor", 0.0) or 0.0)
        transportadora = getattr(pedido, "frete_transportadora", None) or "Não informado"
        status = getattr(pedido, "status", None) or "Não informado"
        nome_cliente = getattr(getattr(pedido, "cliente", None), "nome", None) or "Cliente"

        # Protege todos os itens do pedido
        itens_protegidos = []
        for item in getattr(pedido, "itens", []):
            item_dict = {
                "nome_produto": getattr(item, "nome_produto", "Produto") or "Produto",
                "quantidade": int(getattr(item, "quantidade", 1) or 1),
                "preco_total": float(getattr(item, "preco_total", 0.0) or 0.0),
            }
            itens_protegidos.append(item_dict)

        # Debug
        print("DEBUG ITENS:", itens_protegidos)
        print("DADOS DO PEDIDO:", total, frete_valor, status, nome_cliente)

        assunto = f"Pedido #{pedido_id} confirmado - Maria Raisa"

        corpo_html = render_template(
            "email_confirmacao.html",
            pedido=pedido,
            itens=itens_protegidos,  # <---- agora vai como variável separada!
            total=total,
            frete_valor=frete_valor,
            transportadora=transportadora,
            status=status,
            nome_cliente=nome_cliente
        )

        msg = Message(
            subject=assunto,
            recipients=[destinatario],
            html=corpo_html,
            sender=current_app.config.get('MAIL_USERNAME', 'contato@mariaraisa.com')
        )

        # Corpo do e-mail em texto puro
        msg.body = f"""
Olá {nome_cliente},

Seu pedido #{pedido_id} foi confirmado com sucesso!

Resumo do Pedido:
- Total com frete: R$ {total:.2f}
- Transportadora: {transportadora}
- Frete: R$ {frete_valor:.2f}
- Status: {status}

Você pode acompanhar seu pedido acessando sua conta na Maria Raisa.

Obrigado por comprar com a gente 💖

Equipe Maria Raisa
"""

        print("CORPO DO EMAIL:", msg.body)

        mail.send(msg)

    except Exception as e:
        current_app.logger.warning(f"Erro ao enviar e-mail: {e}")
