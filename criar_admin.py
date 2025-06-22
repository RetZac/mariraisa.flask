from app import create_app
from app.extensions import db
from app.models import Admin
from werkzeug.security import generate_password_hash
from getpass import getpass

app = create_app()

with app.app_context():
    email = input("Email: ").strip()
    senha = input ("Senha: ")

    if not email or not senha:
        print("⚠️ E-mail e senha são obrigatórios.")
    elif Admin.query.filter_by(email=email).first():
        print("⚠️ Já existe um admin com esse e-mail.")
    else:
        novo_admin = Admin(email=email, senha=generate_password_hash(senha))
        db.session.add(novo_admin)
        db.session.commit()
        print("✅ Admin criado com sucesso.")
