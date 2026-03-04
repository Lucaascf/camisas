"""Rotas do blueprint shop."""

from flask import abort, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db, limiter
from app.blueprints.shop import shop_bp
from app.models import Category, Marca, Tecido, Product, ProductVariant, SolicitacaoEncomenda

PRODUTOS_POR_PAGINA = 12


@shop_bp.route('/')
@shop_bp.route('/<slug>')
def listagem(slug=None):
    """Listagem de produtos — todos ou filtrados por categoria/filtro/marca, com paginação."""
    categoria = None
    pagina = request.args.get('pagina', 1, type=int)
    filtro = request.args.get('filtro', '').strip()
    marca_slug = request.args.get('marca', '').strip()
    tecido_slug = request.args.get('tecido', '').strip()

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

    # Resolver objetos de marca e tecido primeiro
    marca_atual = Marca.query.filter_by(slug=marca_slug).first() if marca_slug else None
    tecido_atual = Tecido.query.filter_by(slug=tecido_slug).first() if tecido_slug else None

    # Marcas disponíveis = filtradas pelo tecido selecionado (filtros cascata)
    query_para_marcas = query
    if tecido_atual:
        query_para_marcas = query_para_marcas.filter(Product.tecido_id == tecido_atual.id)
    ids_para_marcas = query_para_marcas.with_entities(Product.id).subquery()
    marcas_disponiveis = (
        Marca.query
        .join(Product, Product.marca_id == Marca.id)
        .filter(Product.id.in_(ids_para_marcas))
        .distinct()
        .order_by(Marca.nome)
        .all()
    )

    # Tecidos disponíveis = filtrados pela marca selecionada (filtros cascata)
    query_para_tecidos = query
    if marca_atual:
        query_para_tecidos = query_para_tecidos.filter(Product.marca_id == marca_atual.id)
    ids_para_tecidos = query_para_tecidos.with_entities(Product.id).subquery()
    tecidos_disponiveis = (
        Tecido.query
        .join(Product, Product.tecido_id == Tecido.id)
        .filter(Product.id.in_(ids_para_tecidos))
        .distinct()
        .order_by(Tecido.nome)
        .all()
    )

    # Aplicar ambos os filtros na query principal
    if marca_atual:
        query = query.filter(Product.marca_id == marca_atual.id)
    if tecido_atual:
        query = query.filter(Product.tecido_id == tecido_atual.id)

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
        marcas_disponiveis=marcas_disponiveis,
        marca_atual=marca_atual,
        tecidos_disponiveis=tecidos_disponiveis,
        tecido_atual=tecido_atual,
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


@shop_bp.route('/parcelas')
def parcelas():
    """Retorna opções de parcelamento via API do MP (JSON)."""
    from app.blueprints.cart.mercadopago_service import calcular_parcelas
    try:
        preco = float(request.args.get('preco', 0))
    except (ValueError, TypeError):
        return jsonify([])
    if preco <= 0:
        return jsonify([])
    resultado = calcular_parcelas(preco)
    return jsonify(resultado)


@shop_bp.route('/solicitar-encomenda', methods=['POST'])
@login_required
def solicitar_encomenda():
    """Registra interesse do usuário em produto sem estoque."""
    data = request.get_json()
    product_id = data.get('product_id') if data else None
    if not product_id:
        return jsonify(sucesso=False, mensagem='product_id obrigatório'), 400

    produto = Product.query.get_or_404(product_id)

    variant_id = data.get('variant_id') if data else None
    tamanho = None
    if variant_id:
        v = ProductVariant.query.get(variant_id)
        if v and v.product_id == product_id:
            if v.estoque > 0:
                return jsonify(sucesso=False, mensagem='Este tamanho está disponível para compra.')
            tamanho = v.tamanho
    elif data:
        tamanho = data.get('tamanho') or None
        if tamanho:
            v_disp = ProductVariant.query.filter_by(
                product_id=product_id, tamanho=tamanho, ativo=True
            ).filter(ProductVariant.estoque > 0).first()
            if v_disp:
                return jsonify(sucesso=False, mensagem='Este tamanho está disponível para compra.')

    existente = SolicitacaoEncomenda.query.filter_by(
        user_id=current_user.id, product_id=product_id
    ).first()

    if not existente:
        solicitacao = SolicitacaoEncomenda(user_id=current_user.id, product_id=product_id, tamanho=tamanho)
        db.session.add(solicitacao)
        db.session.commit()
        from app.blueprints.shop.email_service import enviar_email_encomenda_confirmada
        enviar_email_encomenda_confirmada(current_user, produto, tamanho=tamanho)

    return jsonify(sucesso=True)


@shop_bp.route('/produto/<slug>')
def produto(slug):
    """Página de detalhe de um produto."""
    produto = Product.query.filter_by(slug=slug, ativo=True).first_or_404()
    return render_template('shop/produto.html', produto=produto)
