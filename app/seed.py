"""Script de seed para popular o banco de dados com dados de exemplo."""

import click
from flask.cli import with_appcontext

from app import db
from app.models import Category, Product, User


def seed_db():
    """Popula o banco com categorias, produtos e admin."""

    # Limpa dados existentes (ordem importa por causa das FKs)
    Product.query.delete()
    Category.query.delete()
    User.query.delete()

    # --- Categorias ---
    categorias = {
        'social': Category(
            nome='Social',
            slug='social',
            descricao='Camisas sociais para ocasiões formais e profissionais.',
            imagem_url='/static/img/categorias/social.jpg',
        ),
        'polo': Category(
            nome='Polo',
            slug='polo',
            descricao='Polos elegantes para o dia a dia com estilo.',
            imagem_url='/static/img/categorias/polo.jpg',
        ),
        'casual': Category(
            nome='Casual',
            slug='casual',
            descricao='Camisas casuais para momentos de descontração com classe.',
            imagem_url='/static/img/categorias/casual.jpg',
        ),
        'linho': Category(
            nome='Linho',
            slug='linho',
            descricao='Camisas de linho para conforto e sofisticação.',
            imagem_url='/static/img/categorias/linho.jpg',
        ),
    }

    for cat in categorias.values():
        db.session.add(cat)

    db.session.flush()  # gera IDs

    # --- Produtos ---
    produtos = [
        # Destaques (home)
        Product(
            nome='Camisa Slim Branca',
            slug='camisa-slim-branca',
            descricao='Camisa social slim fit em algodão egípcio branco. Colarinho italiano, punhos duplos para abotoaduras. Acabamento premium com botões de madrepérola.',
            preco=289.90,
            imagem_url='/static/img/produtos/camisa-slim-branca.jpg',
            categoria_id=categorias['social'].id,
            destaque=True,
            novo=True,
            estoque=25,
        ),
        Product(
            nome='Polo Classic Azul Marinho',
            slug='polo-classic-azul-marinho',
            descricao='Polo clássica em piquet de algodão premium. Corte regular, gola em ribana reforçada. Bordado discreto no peito.',
            preco=219.90,
            imagem_url='/static/img/produtos/polo-classic-azul-marinho.jpg',
            categoria_id=categorias['polo'].id,
            destaque=True,
            estoque=30,
        ),
        Product(
            nome='Camisa Linho Off-White',
            slug='camisa-linho-off-white',
            descricao='Camisa em linho puro off-white. Corte relaxed fit, perfeita para o verão. Toque macio e caimento natural.',
            preco=349.90,
            preco_promocional=279.90,
            imagem_url='/static/img/produtos/camisa-linho-off-white.jpg',
            categoria_id=categorias['casual'].id,
            destaque=True,
            estoque=15,
        ),
        Product(
            nome='Camisa Francesa Azul Claro',
            slug='camisa-francesa-azul-claro',
            descricao='Camisa social com colarinho francês em algodão fio 120. Azul claro clássico, ideal para ambientes corporativos.',
            preco=329.90,
            imagem_url='/static/img/produtos/camisa-francesa-azul-claro.jpg',
            categoria_id=categorias['social'].id,
            destaque=True,
            estoque=20,
        ),
        # Produtos extras
        Product(
            nome='Polo Listrada Verde',
            slug='polo-listrada-verde',
            descricao='Polo com listras horizontais em tons de verde. Algodão macio, corte moderno.',
            preco=199.90,
            imagem_url='/static/img/produtos/polo-listrada-verde.jpg',
            categoria_id=categorias['polo'].id,
            estoque=18,
        ),
        Product(
            nome='Camisa Casual Xadrez',
            slug='camisa-casual-xadrez',
            descricao='Camisa casual em xadrez discreto azul e branco. Tecido leve, perfeita para o final de semana.',
            preco=259.90,
            imagem_url='/static/img/produtos/camisa-casual-xadrez.jpg',
            categoria_id=categorias['casual'].id,
            estoque=22,
        ),
        Product(
            nome='Camisa Linho Azul Cobalto',
            slug='camisa-linho-azul-cobalto',
            descricao='Camisa de linho em azul cobalto vibrante. Perfeita para eventos ao ar livre.',
            preco=339.90,
            preco_promocional=289.90,
            imagem_url='/static/img/produtos/camisa-linho-azul-cobalto.jpg',
            categoria_id=categorias['linho'].id,
            estoque=10,
        ),
        Product(
            nome='Camisa Social Rosa Claro',
            slug='camisa-social-rosa-claro',
            descricao='Camisa social slim em rosa claro. Tecido anti-amassamento, ideal para o dia a dia corporativo.',
            preco=299.90,
            imagem_url='/static/img/produtos/camisa-social-rosa-claro.jpg',
            categoria_id=categorias['social'].id,
            novo=True,
            estoque=28,
        ),
    ]

    for produto in produtos:
        db.session.add(produto)

    # --- Admin ---
    admin = User(
        nome='Administrador',
        email='admin@ferrato.com.br',
        admin=True,
    )
    admin.set_senha('admin123')
    db.session.add(admin)

    db.session.commit()
    print('Seed concluído com sucesso!')
    print(f'  - {len(categorias)} categorias')
    print(f'  - {len(produtos)} produtos')
    print(f'  - 1 usuário admin (admin@ferrato.com.br / admin123)')


@click.command('seed')
@with_appcontext
def seed_command():
    """Popula o banco de dados com dados de exemplo."""
    seed_db()


def register_commands(app):
    """Registra comandos CLI na aplicação."""
    app.cli.add_command(seed_command)


if __name__ == '__main__':
    from app import criar_app

    app = criar_app()
    with app.app_context():
        seed_db()
