from app import create_app, db
from app.models import Cliente

app = create_app()

with app.app_context():
    cliente = Cliente.query.filter_by(email="isacnogueiraa9@gmail.com").first()
    if cliente:
        db.session.delete(cliente)
        db.session.commit()
        print(f"Cliente {cliente.email} apagado!")
    else:
        print("Cliente não encontrado.")
