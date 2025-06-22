"""add codigo to Produto

Revision ID: 5a6126d4e088
Revises: a5ccc77e3c5f
Create Date: 2025-05-27 21:26:22.527903

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5a6126d4e088'
down_revision = 'a5ccc77e3c5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('produtos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('codigo', sa.String(length=50), nullable=True))
        batch_op.create_unique_constraint('uq_codigo_produto', ['codigo'])


def downgrade():
    with op.batch_alter_table('produtos', schema=None) as batch_op:
        batch_op.drop_constraint('uq_codigo_produto', type_='unique')
        batch_op.drop_column('codigo')


    # ### end Alembic commands ###
