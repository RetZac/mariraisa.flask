import os
from flask import Flask
from .extensions import db, login_manager, migrate
from .models import Admin, Cliente
from flask_mail import Mail
from dotenv import load_dotenv

load_dotenv()
mail = Mail()
basedir = os.path.abspath(os.path.dirname(__file__))

def create_app():
    app = Flask(__name__)

    # Configurações principais
    app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../instance/produtos.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'images', 'banners')

    # Configurações de e-mail (Gmail com TLS)
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

    # Inicializa o Mail e salva na aplicação
    mail.init_app(app)
    app.extensions['mail'] = mail

    # Inicializa extensões
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'routes.login'
    migrate.init_app(app, db)

    # Carrega usuário (Admin ou Cliente)
    @login_manager.user_loader
    def load_user(user_id):
        return Admin.query.get(user_id) or Cliente.query.get(user_id)

    # Blueprint das rotas
    from app.routes import routes
    app.register_blueprint(routes)

    return app
