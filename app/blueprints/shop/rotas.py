"""Rotas do blueprint shop."""

from flask import abort, jsonify, render_template, request
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db, limiter
from app.blueprints.shop import shop_bp
from app.models import Category, Product, ProductVariant

PRODUTOS_POR_PAGINA = 12


@shop_bp.route('/')
@shop_bp.route('/<slug>')
def listagem(slug=None):
    """Listagem de produtos — todos ou filtrados por categoria/filtro, com paginação."""
    categoria = None
    pagina = request.args.get('pagina', 1, type=int)
    filtro = request.args.get('filtro', '').strip()

    if slug:
        categoria = Category.query.filter_by(slug=slug).first_or_404()
        query = Product.query.filter_by(categoria_id=categoria.id, ativo=True)
    elif filtro == 'promocao':
        query = Product.query.filter(
            Product.ativo == True,
            Product.preco_promocional.isnot(None),
        )
    elif filtro == 'novos':
        query = Product.query.filter(
            Product.ativo == True,
            Product.novo == True,
        )
    elif filtro == 'ultimas':
        estoque_sq = (
            db.session.query(
                ProductVariant.product_id,
                func.sum(ProductVariant.estoque).label('total'),
            )
            .filter(ProductVariant.ativo == True)
            .group_by(ProductVariant.product_id)
            .subquery()
        )
        query = (
            Product.query
            .join(estoque_sq, Product.id == estoque_sq.c.product_id)
            .filter(
                Product.ativo == True,
                estoque_sq.c.total > 0,
                estoque_sq.c.total <= 5,
            )
        )
    else:
        query = Product.query.filter_by(ativo=True)

    paginacao = query.options(joinedload(Product.variantes)).order_by(Product.criado_em.desc()).paginate(
        page=pagina, per_page=PRODUTOS_POR_PAGINA, error_out=False
    )
    produtos = paginacao.items

    return render_template(
        'shop/listagem.html',
        categoria=categoria,
        produtos=produtos,
        paginacao=paginacao,
        filtro=filtro,
    )


@shop_bp.route('/busca')
@limiter.limit("30 per minute")
def busca():
    """Busca de produtos por texto."""
    termo = request.args.get('q', '').strip()
    pagina = request.args.get('pagina', 1, type=int)
    produtos = []
    paginacao = None

    if termo:
        like = f'%{termo}%'
        query = Product.query.filter(
            Product.ativo == True,
            db.or_(
                Product.nome.ilike(like),
                Product.descricao.ilike(like),
            )
        )
        paginacao = query.options(joinedload(Product.variantes)).order_by(Product.criado_em.desc()).paginate(
            page=pagina, per_page=PRODUTOS_POR_PAGINA, error_out=False
        )
        produtos = paginacao.items

    return render_template(
        'shop/busca.html',
        termo=termo,
        produtos=produtos,
        paginacao=paginacao,
    )


@shop_bp.route('/busca/json')
@limiter.limit("30 per minute")
def busca_json():
    """Busca de produtos — retorna JSON para live search."""
    termo = request.args.get('q', '').strip()
    if not termo or len(termo) < 2:
        return jsonify(produtos=[], total=0)

    like = f'%{termo}%'
    produtos = Product.query.filter(
        Product.ativo == True,
        db.or_(
            Product.nome.ilike(like),
            Product.descricao.ilike(like),
        )
    ).order_by(Product.criado_em.desc()).limit(24).all()

    return jsonify(
        total=len(produtos),
        produtos=[{
            'nome': p.nome,
            'slug': p.slug,
            'categoria': p.categoria.nome if p.categoria else '',
            'preco': float(p.preco),
            'preco_promocional': float(p.preco_promocional) if p.preco_promocional else None,
            'em_promocao': p.em_promocao,
            'percentual_desconto': p.percentual_desconto,
            'imagem': p.imagem_principal,
            'estoque_total': p.estoque_total,
            'novo': p.novo,
        } for p in produtos]
    )


@shop_bp.route('/produto/<slug>')
def produto(slug):
    """Página de detalhe de um produto."""
    produto = Product.query.filter_by(slug=slug, ativo=True).first_or_404()
    return render_template('shop/produto.html', produto=produto)
