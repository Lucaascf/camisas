"""Rotas do painel administrativo."""

import logging
import re
from urllib.parse import urlparse

from flask import render_template, redirect, url_for, flash, request, session, jsonify, current_app

from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.blueprints.admin import admin_bp
from app.forms import ProductForm, CategoryForm, MarcaForm, TecidoForm
from app.models import Cupom, Product, Category, Marca, Tecido, ProductImage, ProductImageURL, ProductVariant, Order, User, CartItem

logger = logging.getLogger(__name__)


def _slug_unico(model_cls, base_slug, exclude_id=None):
    """Garante unicidade do slug adicionando sufixo numérico se necessário."""
    slug = base_slug
    counter = 2
    while True:
        q = model_cls.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(model_cls.id != exclude_id)
        if not q.first():
            return slug
        slug = f'{base_slug}-{counter}'
        counter += 1


@admin_bp.before_request
def verificar_acesso_admin():
    """Bloqueia todas as rotas admin exceto login/logout."""
    if request.endpoint in ('admin.login_admin', 'admin.logout_admin'):
        return
    if not session.get('admin_autenticado'):
        return redirect(url_for('admin.login_admin'))


@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login_admin():
    if session.get('admin_autenticado'):
        return redirect(url_for('admin.dashboard'))
    erro = None
    if request.method == 'POST':
        chave = request.form.get('chave', '')
        admin_key = current_app.config.get('ADMIN_ACCESS_KEY', '')
        if not admin_key or chave != admin_key:
            erro = 'Chave de acesso inválida.'
        else:
            session.clear()
            session['admin_autenticado'] = True
            return redirect(url_for('admin.dashboard'))
    return render_template('admin/login.html', erro=erro)


@admin_bp.route('/logout')
def logout_admin():
    session.pop('admin_autenticado', None)
    return redirect(url_for('admin.login_admin'))


@admin_bp.route('/')
def dashboard():
    """Dashboard admin com lista de produtos e estatísticas."""
    from sqlalchemy import func
    produtos = Product.query.order_by(Product.criado_em.desc()).all()

    # Estatísticas
    total_pedidos = Order.query.count()
    pedidos_pendentes = Order.query.filter(Order.status.in_(['pendente', 'aguardando_pagamento'])).count()
    receita_total = db.session.query(
        func.coalesce(func.sum(Order.total), 0)
    ).filter(Order.status.in_(['pago', 'preparando', 'enviado', 'entregue'])).scalar()
    total_usuarios = User.query.count()

    # Produtos com estoque baixo (variantes ativas com estoque < 5)
    from app.models import ProductVariant
    estoque_baixo = db.session.query(Product).join(
        ProductVariant, Product.id == ProductVariant.product_id
    ).filter(
        ProductVariant.ativo == True,
        ProductVariant.estoque < 5,
        Product.ativo == True
    ).distinct().all()

    categorias = Category.query.order_by(Category.nome).all()

    return render_template(
        'admin/dashboard.html',
        produtos=produtos,
        categorias=categorias,
        total_pedidos=total_pedidos,
        pedidos_pendentes=pedidos_pendentes,
        receita_total=receita_total,
        total_usuarios=total_usuarios,
        estoque_baixo=estoque_baixo,
    )


@admin_bp.route('/pedidos')
def pedidos():
    """Listar todos os pedidos com filtro por status e paginação."""
    status_filtro = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    query = Order.query.order_by(Order.criado_em.desc())
    if status_filtro:
        query = query.filter_by(status=status_filtro)
    paginacao = query.paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/pedidos.html',
                           pedidos=paginacao.items,
                           paginacao=paginacao,
                           status_filtro=status_filtro)


@admin_bp.route('/pedidos/<int:id>')
def pedido_detalhe(id):
    """Detalhe de um pedido."""
    pedido = Order.query.get_or_404(id)
    return render_template('admin/pedido_detalhe.html', pedido=pedido)


@admin_bp.route('/pedidos/<int:id>/status', methods=['POST'])
def pedido_atualizar_status(id):
    """Atualizar status de um pedido."""
    pedido = Order.query.get_or_404(id)
    novo_status = request.form.get('status')
    codigo_rastreio = request.form.get('codigo_rastreio', '').strip()

    status_validos = ['pendente', 'aguardando_pagamento', 'pago', 'preparando', 'enviado', 'entregue', 'cancelado']
    if novo_status not in status_validos:
        flash('Status inválido.', 'error')
        return redirect(url_for('admin.pedido_detalhe', id=id))

    pedido.status = novo_status
    if codigo_rastreio:
        pedido.codigo_rastreio = codigo_rastreio

    db.session.commit()

    if novo_status == 'enviado':
        from threading import Thread
        from app.blueprints.cart.email_pedido_service import enviar_email_pedido_enviado
        app = current_app._get_current_object()
        pedido_id = pedido.id
        def _enviar_em_background(app, pedido_id):
            with app.app_context():
                try:
                    from app.models import Order
                    pedido_fresh = Order.query.get(pedido_id)
                    if pedido_fresh:
                        enviar_email_pedido_enviado(pedido_fresh)
                except Exception as e:
                    logger.error("EMAIL PEDIDO: erro ao enviar notificação de envio — %s", e)
        Thread(target=_enviar_em_background, args=(app, pedido_id), daemon=True).start()

    flash(f'Status do pedido #{pedido.id} atualizado para "{novo_status}".', 'success')
    return redirect(url_for('admin.pedido_detalhe', id=id))


@admin_bp.route('/pedidos/<int:id>/verificar-pagamento', methods=['POST'])
def pedido_verificar_pagamento(id):
    """Consulta o MP e confirma (ou cancela) um pedido manualmente."""
    from app.blueprints.cart import mercadopago_service
    from app.blueprints.cart.email_pedido_service import enviar_email_pedido_confirmado

    pedido = Order.query.get_or_404(id)
    if pedido.status != 'aguardando_pagamento' or not pedido.mercadopago_preference_id:
        flash('Este pedido não está aguardando pagamento.', 'warning')
        return redirect(url_for('admin.pedido_detalhe', id=id))

    try:
        resultado = mercadopago_service.consultar_pagamento(pedido.mercadopago_preference_id)
        if resultado['status'] == 'approved':
            for item in pedido.items:
                if item.variant:
                    item.variant.estoque -= item.quantidade
                else:
                    item.product.estoque -= item.quantidade
            pedido.status = 'pago'
            pedido.mercadopago_payment_id = resultado['payment_id']
            db.session.commit()
            try:
                enviar_email_pedido_confirmado(pedido)
            except Exception as e:
                logger.error('EMAIL PEDIDO: erro — %s', e)
            flash(f'Pagamento confirmado! Pedido #{pedido.id} marcado como pago.', 'success')
        elif resultado['status'] in ('rejected', 'cancelled'):
            pedido.status = 'cancelado'
            db.session.commit()
            flash('Pagamento rejeitado. Pedido marcado como cancelado.', 'error')
        else:
            flash('Pagamento ainda pendente no Mercado Pago.', 'info')
    except Exception as e:
        logger.error('ADMIN VERIFICAR PAGAMENTO: erro — %s', e)
        flash('Erro ao consultar pagamento. Tente novamente.', 'error')

    return redirect(url_for('admin.pedido_detalhe', id=id))


@admin_bp.route('/produtos/novo', methods=['GET', 'POST'])
def novo_produto():
    """Criar novo produto."""
    form = ProductForm()

    if form.validate_on_submit():
        # Gerar slug se vazio
        slug = form.slug.data
        if not slug:
            slug = re.sub(r'[^\w\s-]', '', form.nome.data.lower())
            slug = slug.replace(' ', '-')

        # Criar produto
        produto = Product(
            nome=form.nome.data,
            slug=slug,
            descricao=form.descricao.data,
            preco=form.preco.data,
            preco_promocional=form.preco_promocional.data,
            imagem_url=form.imagem_url.data,
            categoria_id=form.categoria_id.data,
            marca_id=form.marca_id.data if form.marca_id.data != 0 else None,
            tecido_id=form.tecido_id.data if form.tecido_id.data != 0 else None,
            estoque=0,  # Estoque sempre gerenciado pelas variantes
            destaque=form.destaque.data,
            novo=form.novo.data,
            ativo=form.ativo.data
        )

        db.session.add(produto)
        db.session.flush()

        # Processar uploads de imagens
        arquivos = request.files.getlist('imagens')
        if arquivos:
            for ordem, arquivo in enumerate(arquivos):
                if arquivo and arquivo.filename:
                    imagem = ProductImage(
                        product_id=produto.id,
                        filename=arquivo.filename,
                        mimetype=arquivo.mimetype,
                        data=arquivo.read(),
                        ordem=ordem
                    )
                    db.session.add(imagem)

        # Processar URLs de imagens
        urls = [u.strip() for u in request.form.getlist('urls') if u.strip()]
        for idx, url in enumerate(urls):
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                flash(f'URL inválida ignorada: {url[:50]}', 'warning')
                continue
            db.session.add(ProductImageURL(
                product_id=produto.id,
                url=url,
                ordem=idx
            ))

        db.session.commit()

        total_imagens = len(produto.imagens) if produto.imagens else 0
        flash(f'Produto "{produto.nome}" criado com sucesso! {total_imagens} imagem(ns) adicionada(s).', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/produto_form.html', form=form, produto=None)


@admin_bp.route('/produtos/<int:id>/editar', methods=['GET', 'POST'])
def editar_produto(id):
    """Editar produto existente."""
    produto = Product.query.get_or_404(id)

    # Só popular com obj=produto no GET, não no POST
    if request.method == 'GET':
        form = ProductForm(produto_id=produto.id, obj=produto)
    else:
        form = ProductForm(produto_id=produto.id)


    if form.validate_on_submit():
        # Gerar slug se vazio
        slug = form.slug.data
        if not slug:
            slug = re.sub(r'[^\w\s-]', '', form.nome.data.lower())
            slug = slug.replace(' ', '-')

        # Atualizar produto
        produto.nome = form.nome.data
        produto.slug = slug
        produto.descricao = form.descricao.data
        produto.preco = form.preco.data
        produto.preco_promocional = form.preco_promocional.data
        produto.imagem_url = form.imagem_url.data
        produto.categoria_id = form.categoria_id.data
        produto.marca_id = form.marca_id.data if form.marca_id.data != 0 else None
        produto.tecido_id = form.tecido_id.data if form.tecido_id.data != 0 else None
        produto.estoque = 0  # Estoque sempre gerenciado pelas variantes
        produto.destaque = form.destaque.data
        produto.novo = form.novo.data
        produto.ativo = form.ativo.data

        # Processar novos uploads de imagens
        arquivos = request.files.getlist('imagens')
        if arquivos:
            # Obter a ordem máxima atual
            max_ordem = max([img.ordem for img in produto.imagens], default=-1)

            for idx, arquivo in enumerate(arquivos):
                if arquivo and arquivo.filename:
                    imagem = ProductImage(
                        product_id=produto.id,
                        filename=arquivo.filename,
                        mimetype=arquivo.mimetype,
                        data=arquivo.read(),
                        ordem=max_ordem + idx + 1
                    )
                    db.session.add(imagem)

        db.session.commit()

        total_imagens = len(produto.imagens)
        flash(f'Produto "{produto.nome}" atualizado com sucesso!', 'success')
        return redirect(url_for('admin.dashboard'))

    cores_produto = sorted({v.cor for v in produto.variantes if v.cor})
    return render_template('admin/produto_form.html', form=form, produto=produto, cores_produto=cores_produto)


@admin_bp.route('/produtos/<int:id>/toggle-ativo', methods=['POST'])
def toggle_ativo(id):
    """Ativar/desativar produto (soft delete)."""
    produto = Product.query.get_or_404(id)
    produto.ativo = not produto.ativo
    db.session.commit()

    status = 'ativado' if produto.ativo else 'desativado'
    flash(f'Produto "{produto.nome}" {status} com sucesso!', 'info')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/produtos/<int:id>/deletar', methods=['POST'])
def deletar_produto(id):
    """Deletar produto permanentemente."""
    from app.models import CartItem, OrderItem, Wishlist
    produto = Product.query.get_or_404(id)

    if OrderItem.query.filter_by(product_id=id).first():
        flash(
            f'O produto "{produto.nome}" está associado a pedidos existentes e não pode ser deletado. '
            'Use "Desativar" para ocultá-lo do site.',
            'error'
        )
        return redirect(url_for('admin.dashboard'))

    nome = produto.nome
    CartItem.query.filter_by(product_id=id).delete()
    Wishlist.query.filter_by(product_id=id).delete()
    ProductVariant.query.filter_by(product_id=id).delete()
    ProductImage.query.filter_by(product_id=id).delete()
    ProductImageURL.query.filter_by(product_id=id).delete()
    db.session.delete(produto)
    db.session.commit()

    flash(f'Produto "{nome}" deletado com sucesso.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/produtos/imagem/<int:image_id>/deletar', methods=['POST'])
def deletar_imagem(image_id):
    """Deletar uma imagem de produto."""
    imagem = ProductImage.query.get_or_404(image_id)
    produto_id = imagem.product_id
    produto_nome = imagem.product.nome

    db.session.delete(imagem)
    db.session.commit()

    flash(f'Imagem removida de "{produto_nome}" com sucesso!', 'success')
    return redirect(url_for('admin.editar_produto', id=produto_id))


@admin_bp.route('/produtos/<int:id>/adicionar-imagens', methods=['POST'])
def adicionar_imagens(id):
    """Adicionar imagens a um produto existente."""
    produto = Product.query.get_or_404(id)
    arquivos = request.files.getlist('imagens')

    if not arquivos or not any(f.filename for f in arquivos):
        flash('Nenhum arquivo foi selecionado!', 'error')
        return redirect(url_for('admin.editar_produto', id=id))

    max_ordem = max([img.ordem for img in produto.imagens], default=-1)
    contador = 0

    for idx, arquivo in enumerate(arquivos):
        if arquivo and arquivo.filename:
            imagem = ProductImage(
                product_id=produto.id,
                filename=arquivo.filename,
                mimetype=arquivo.mimetype,
                data=arquivo.read(),
                ordem=max_ordem + idx + 1
            )
            db.session.add(imagem)
            contador += 1

    try:
        db.session.commit()
        flash(f'{contador} imagem(ns) adicionada(s) com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar imagens: {str(e)}', 'error')

    return redirect(url_for('admin.editar_produto', id=id))


@admin_bp.route('/produtos/<int:id>/adicionar-url-imagens', methods=['POST'])
def adicionar_url_imagens(id):
    """Adicionar imagens por URL a um produto existente."""
    produto = Product.query.get_or_404(id)
    urls = request.form.getlist('urls')

    max_ordem = max(
        [img.ordem for img in produto.imagens] + [img.ordem for img in produto.imagens_url],
        default=-1
    )
    contador = 0

    for idx, url in enumerate(urls):
        url = url.strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                flash(f'URL inválida ignorada: {url[:50]}', 'warning')
                continue
            imagem = ProductImageURL(
                product_id=produto.id,
                url=url,
                ordem=max_ordem + idx + 1
            )
            db.session.add(imagem)
            contador += 1

    try:
        db.session.commit()
        if contador:
            flash(f'{contador} URL(s) de imagem adicionada(s) com sucesso!', 'success')
        else:
            flash('Nenhuma URL válida foi informada.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar URLs: {str(e)}', 'error')

    return redirect(url_for('admin.editar_produto', id=id))


@admin_bp.route('/produtos/<int:id>/reordenar-imagens', methods=['POST'])
def reordenar_imagens(id):
    """Reordenar imagens de um produto (upload + URL)."""
    produto = Product.query.get_or_404(id)
    dados = request.get_json()
    if not dados or 'imagens' not in dados:
        return jsonify(sucesso=False, mensagem='Dados inválidos'), 400

    try:
        for item in dados['imagens']:
            if item['type'] == 'upload':
                img = ProductImage.query.get(item['id'])
                if img and img.product_id == produto.id:
                    img.ordem = item['ordem']
            elif item['type'] == 'url':
                img = ProductImageURL.query.get(item['id'])
                if img and img.product_id == produto.id:
                    img.ordem = item['ordem']
        db.session.commit()
        return jsonify(sucesso=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(sucesso=False, mensagem=str(e)), 500


@admin_bp.route('/produtos/<int:prod_id>/imagens/<int:img_id>/cor', methods=['POST'])
def definir_cor_imagem(prod_id, img_id):
    """Definir a cor associada a uma imagem (upload ou URL)."""
    dados = request.get_json() or {}
    tipo = dados.get('tipo')
    cor = dados.get('cor', '')
    if tipo == 'upload':
        img = ProductImage.query.get_or_404(img_id)
    elif tipo == 'url':
        img = ProductImageURL.query.get_or_404(img_id)
    else:
        return jsonify(sucesso=False, mensagem='Tipo inválido'), 400
    if img.product_id != prod_id:
        return jsonify(sucesso=False), 403
    img.cor = cor
    db.session.commit()
    return jsonify(sucesso=True)


@admin_bp.route('/imagem-url/<int:image_id>/deletar', methods=['POST'])
def deletar_imagem_url(image_id):
    """Deletar uma imagem de produto por URL."""
    imagem = ProductImageURL.query.get_or_404(image_id)
    produto_id = imagem.product_id
    produto_nome = imagem.produto.nome

    db.session.delete(imagem)
    db.session.commit()

    flash(f'URL de imagem removida de "{produto_nome}" com sucesso!', 'success')
    return redirect(url_for('admin.editar_produto', id=produto_id))


@admin_bp.route('/produtos/<int:id>/variantes', methods=['POST'])
def salvar_variantes(id):
    """Salvar/atualizar variantes (tamanho + cor) de um produto."""
    produto = Product.query.get_or_404(id)

    dados = request.get_json()
    if not dados or 'variantes' not in dados:
        return jsonify(sucesso=False, mensagem='Dados inválidos'), 400

    variantes_dados = dados['variantes']
    variantes_criadas = []

    try:
        with db.session.no_autoflush:  # evita autoflush prematuro durante queries no loop
            ids_submetidos = {int(v['id']) for v in variantes_dados if v.get('id')}

            # Deletar variantes removidas da UI (não presentes na lista submetida)
            for v in list(produto.variantes):
                if v.id not in ids_submetidos:
                    CartItem.query.filter_by(variant_id=v.id).update({'variant_id': None})
                    db.session.delete(v)

            for v_data in variantes_dados:
                tamanho = v_data.get('tamanho') or ''
                cor = v_data.get('cor') or ''
                cor_hex = v_data.get('cor_hex') or ''
                ativo = v_data.get('ativo', False)
                estoque = v_data.get('estoque', 0)
                variant_id = v_data.get('id')

                if variant_id:
                    # Atualizar variante existente por ID
                    variante = ProductVariant.query.get(variant_id)
                    if variante and variante.product_id == produto.id:
                        # Verificar conflito com outra variante existente
                        conflito = ProductVariant.query.filter(
                            ProductVariant.product_id == produto.id,
                            ProductVariant.tamanho == tamanho,
                            ProductVariant.cor == cor,
                            ProductVariant.id != variant_id
                        ).first()
                        if conflito:
                            db.session.rollback()
                            return jsonify(
                                sucesso=False,
                                mensagem=f'Já existe outra variante com tamanho "{tamanho}" e cor "{cor or "sem cor"}".'
                            ), 400
                        variante.tamanho = tamanho
                        variante.cor = cor
                        variante.cor_hex = cor_hex
                        variante.ativo = ativo
                        variante.estoque = estoque if ativo else 0
                        variantes_criadas.append({
                            'id': variante.id,
                            'tamanho': variante.tamanho,
                            'cor': variante.cor,
                            'cor_hex': variante.cor_hex,
                            'estoque': variante.estoque,
                            'ativo': variante.ativo
                        })
                else:
                    # Buscar variante existente pela combinação (product_id, tamanho, cor)
                    variante = ProductVariant.query.filter_by(
                        product_id=produto.id,
                        tamanho=tamanho,
                        cor=cor
                    ).first()

                    if variante:
                        variante.cor_hex = cor_hex
                        variante.ativo = ativo
                        variante.estoque = estoque if ativo else 0
                    else:
                        # Criar nova variante apenas se estiver ativa
                        if ativo:
                            variante = ProductVariant(
                                product_id=produto.id,
                                tamanho=tamanho,
                                cor=cor,
                                cor_hex=cor_hex,
                                estoque=estoque,
                                ativo=True
                            )
                            db.session.add(variante)
                            db.session.flush()

                    if variante:
                        variantes_criadas.append({
                            'id': variante.id,
                            'tamanho': variante.tamanho,
                            'cor': variante.cor,
                            'cor_hex': variante.cor_hex,
                            'estoque': variante.estoque,
                            'ativo': variante.ativo
                        })

        db.session.commit()

        return jsonify(
            sucesso=True,
            mensagem='Variantes salvas com sucesso!',
            variantes=variantes_criadas
        )

    except IntegrityError:
        db.session.rollback()
        return jsonify(sucesso=False, mensagem='Combinação de tamanho e cor já existe neste produto.'), 400
    except Exception as e:
        db.session.rollback()
        return jsonify(sucesso=False, mensagem=str(e)), 500


@admin_bp.route('/produtos/<int:prod_id>/variantes/<int:var_id>/desativar', methods=['POST'])
def desativar_variante(prod_id, var_id):
    """Desativar uma variante individual."""
    variante = ProductVariant.query.get_or_404(var_id)
    if variante.product_id != prod_id:
        return jsonify(sucesso=False), 403
    CartItem.query.filter_by(variant_id=variante.id).update({'variant_id': None})
    db.session.delete(variante)
    db.session.commit()
    return jsonify(sucesso=True)


# ==================== CATEGORIAS ====================

@admin_bp.route('/categorias')
def categorias():
    """Listar todas as categorias."""
    cats = Category.query.order_by(Category.nome).all()
    return render_template('admin/categorias.html', categorias=cats)


@admin_bp.route('/categorias/nova', methods=['GET', 'POST'])
def nova_categoria():
    """Criar nova categoria."""
    form = CategoryForm()

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Category, base)

        categoria = Category(
            nome=form.nome.data,
            slug=slug,
            descricao=form.descricao.data,
            imagem_url=form.imagem_url.data or None,
        )
        db.session.add(categoria)
        db.session.commit()

        flash(f'Categoria "{categoria.nome}" criada com sucesso!', 'success')
        return redirect(url_for('admin.categorias'))

    return render_template('admin/categoria_form.html', form=form, categoria=None)


@admin_bp.route('/categorias/<int:id>/editar', methods=['GET', 'POST'])
def editar_categoria(id):
    """Editar categoria existente."""
    categoria = Category.query.get_or_404(id)

    if request.method == 'GET':
        form = CategoryForm(categoria_id=categoria.id, obj=categoria)
    else:
        form = CategoryForm(categoria_id=categoria.id)

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Category, base, exclude_id=categoria.id)

        categoria.nome = form.nome.data
        categoria.slug = slug
        categoria.descricao = form.descricao.data
        categoria.imagem_url = form.imagem_url.data or None
        db.session.commit()

        flash(f'Categoria "{categoria.nome}" atualizada com sucesso!', 'success')
        return redirect(url_for('admin.categorias'))

    return render_template('admin/categoria_form.html', form=form, categoria=categoria)


@admin_bp.route('/categorias/<int:id>/deletar', methods=['POST'])
def deletar_categoria(id):
    """Deletar categoria (apenas se não tiver produtos associados)."""
    categoria = Category.query.get_or_404(id)

    if categoria.products:
        flash(
            f'A categoria "{categoria.nome}" possui {len(categoria.products)} produto(s) '
            'e não pode ser deletada. Mova ou remova os produtos primeiro.',
            'error'
        )
        return redirect(url_for('admin.categorias'))

    nome = categoria.nome
    db.session.delete(categoria)
    db.session.commit()
    flash(f'Categoria "{nome}" deletada com sucesso!', 'success')
    return redirect(url_for('admin.categorias'))


# ==================== MARCAS ====================

@admin_bp.route('/marcas')
def marcas():
    """Listar todas as marcas."""
    todas = Marca.query.order_by(Marca.nome).all()
    return render_template('admin/marcas.html', marcas=todas)


@admin_bp.route('/marcas/nova', methods=['GET', 'POST'])
def nova_marca():
    """Criar nova marca."""
    form = MarcaForm()

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Marca, base)

        marca = Marca(nome=form.nome.data, slug=slug)
        db.session.add(marca)
        db.session.commit()

        flash(f'Marca "{marca.nome}" criada com sucesso!', 'success')
        return redirect(url_for('admin.marcas'))

    return render_template('admin/marca_form.html', form=form, marca=None)


@admin_bp.route('/marcas/<int:id>/editar', methods=['GET', 'POST'])
def editar_marca(id):
    """Editar marca existente."""
    marca = Marca.query.get_or_404(id)

    if request.method == 'GET':
        form = MarcaForm(marca_id=marca.id, obj=marca)
    else:
        form = MarcaForm(marca_id=marca.id)

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Marca, base, exclude_id=marca.id)

        marca.nome = form.nome.data
        marca.slug = slug
        db.session.commit()

        flash(f'Marca "{marca.nome}" atualizada com sucesso!', 'success')
        return redirect(url_for('admin.marcas'))

    return render_template('admin/marca_form.html', form=form, marca=marca)


@admin_bp.route('/marcas/<int:id>/deletar', methods=['POST'])
def deletar_marca(id):
    """Deletar marca (apenas se não tiver produtos associados)."""
    marca = Marca.query.get_or_404(id)

    if marca.products:
        flash(
            f'A marca "{marca.nome}" possui {len(marca.products)} produto(s) '
            'e não pode ser deletada. Remova a marca dos produtos primeiro.',
            'error'
        )
        return redirect(url_for('admin.marcas'))

    nome = marca.nome
    db.session.delete(marca)
    db.session.commit()
    flash(f'Marca "{nome}" deletada com sucesso!', 'success')
    return redirect(url_for('admin.marcas'))


# ==================== TECIDOS ====================

@admin_bp.route('/tecidos')
def tecidos():
    """Listar todos os tecidos."""
    todos = Tecido.query.order_by(Tecido.nome).all()
    return render_template('admin/tecidos.html', tecidos=todos)


@admin_bp.route('/tecidos/novo', methods=['GET', 'POST'])
def novo_tecido():
    """Criar novo tecido."""
    form = TecidoForm()

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Tecido, base)

        tecido = Tecido(nome=form.nome.data, slug=slug)
        db.session.add(tecido)
        db.session.commit()

        flash(f'Tecido "{tecido.nome}" criado com sucesso!', 'success')
        return redirect(url_for('admin.tecidos'))

    return render_template('admin/tecido_form.html', form=form, tecido=None)


@admin_bp.route('/tecidos/<int:id>/editar', methods=['GET', 'POST'])
def editar_tecido(id):
    """Editar tecido existente."""
    tecido = Tecido.query.get_or_404(id)

    if request.method == 'GET':
        form = TecidoForm(tecido_id=tecido.id, obj=tecido)
    else:
        form = TecidoForm(tecido_id=tecido.id)

    if form.validate_on_submit():
        slug = form.slug.data
        if not slug:
            base = re.sub(r'[^\w\s-]', '', form.nome.data.lower()).replace(' ', '-')
            slug = _slug_unico(Tecido, base, exclude_id=tecido.id)

        tecido.nome = form.nome.data
        tecido.slug = slug
        db.session.commit()

        flash(f'Tecido "{tecido.nome}" atualizado com sucesso!', 'success')
        return redirect(url_for('admin.tecidos'))

    return render_template('admin/tecido_form.html', form=form, tecido=tecido)


@admin_bp.route('/tecidos/<int:id>/deletar', methods=['POST'])
def deletar_tecido(id):
    """Deletar tecido (apenas se não tiver produtos associados)."""
    tecido = Tecido.query.get_or_404(id)

    if tecido.products:
        flash(
            f'O tecido "{tecido.nome}" possui {len(tecido.products)} produto(s) '
            'e não pode ser deletado. Remova o tecido dos produtos primeiro.',
            'error'
        )
        return redirect(url_for('admin.tecidos'))

    nome = tecido.nome
    db.session.delete(tecido)
    db.session.commit()
    flash(f'Tecido "{nome}" deletado com sucesso!', 'success')
    return redirect(url_for('admin.tecidos'))


# ==================== USUÁRIOS ====================

# ==================== CUPONS ====================

@admin_bp.route('/cupons')
def cupons():
    """Listar e gerenciar cupons de desconto."""
    cupons_lista = Cupom.query.order_by(Cupom.criado_em.desc()).all()
    total_usuarios = User.query.count()
    return render_template('admin/cupons.html', cupons=cupons_lista, total_usuarios=total_usuarios)


@admin_bp.route('/cupons/novo', methods=['POST'])
def novo_cupom():
    """Criar novo cupom."""
    import secrets as _secrets
    from datetime import datetime as _dt

    desconto = request.form.get('desconto_percentual', '').strip()
    codigo = request.form.get('codigo', '').strip().upper()
    validade_str = request.form.get('validade', '').strip()
    usos_maximos_str = request.form.get('usos_maximos', '').strip()

    # Validar desconto
    try:
        desconto_float = float(desconto)
        if not (1 <= desconto_float <= 90):
            raise ValueError
    except (ValueError, TypeError):
        flash('Percentual de desconto inválido (deve ser entre 1 e 90).', 'error')
        return redirect(url_for('admin.cupons'))

    # Gerar código automático se vazio
    if not codigo:
        codigo = 'FERRATO' + _secrets.token_hex(3).upper()

    # Verificar duplicado
    if Cupom.query.filter_by(codigo=codigo).first():
        flash(f'Já existe um cupom com o código "{codigo}".', 'error')
        return redirect(url_for('admin.cupons'))

    # Validade
    validade = None
    if validade_str:
        try:
            validade = _dt.strptime(validade_str, '%Y-%m-%d')
        except ValueError:
            flash('Data de validade inválida.', 'error')
            return redirect(url_for('admin.cupons'))

    # Usos máximos
    usos_maximos = None
    if usos_maximos_str:
        try:
            usos_maximos = int(usos_maximos_str)
            if usos_maximos < 1:
                raise ValueError
        except ValueError:
            flash('Usos máximos inválido.', 'error')
            return redirect(url_for('admin.cupons'))

    cupom = Cupom(
        codigo=codigo,
        desconto_percentual=desconto_float,
        validade=validade,
        usos_maximos=usos_maximos,
    )
    db.session.add(cupom)
    db.session.commit()

    flash(f'Cupom "{codigo}" criado com {desconto_float:.0f}% de desconto!', 'success')
    return redirect(url_for('admin.cupons'))


@admin_bp.route('/cupons/<int:id>/toggle', methods=['POST'])
def toggle_cupom(id):
    """Ativar/desativar cupom."""
    cupom = Cupom.query.get_or_404(id)
    cupom.ativo = not cupom.ativo
    db.session.commit()
    return jsonify({'ativo': cupom.ativo})


@admin_bp.route('/cupons/<int:id>/deletar', methods=['POST'])
def deletar_cupom(id):
    """Deletar cupom (ou desativar se houver pedidos usando-o)."""
    cupom = Cupom.query.get_or_404(id)
    pedidos_com_cupom = Order.query.filter_by(cupom_codigo=cupom.codigo).first()
    if pedidos_com_cupom:
        cupom.ativo = False
        db.session.commit()
        flash(f'Cupom "{cupom.codigo}" não pode ser deletado pois há pedidos associados. Cupom desativado.', 'warning')
    else:
        codigo = cupom.codigo
        db.session.delete(cupom)
        db.session.commit()
        flash(f'Cupom "{codigo}" deletado com sucesso.', 'success')
    return redirect(url_for('admin.cupons'))


@admin_bp.route('/cupons/<int:id>/enviar-email', methods=['POST'])
def enviar_email_cupom(id):
    """Enviar cupom por email para todos os usuários cadastrados."""
    cupom = Cupom.query.get_or_404(id)
    usuarios = User.query.all()
    if not usuarios:
        return jsonify({'enviado': 0, 'mensagem': 'Nenhum usuário cadastrado.'})

    from app.blueprints.auth.email_service import enviar_cupom_usuarios
    enviar_cupom_usuarios(cupom, usuarios)

    return jsonify({'enviado': len(usuarios), 'mensagem': f'Email enviado para {len(usuarios)} usuário(s).'})


# ==================== FRETE ====================

@admin_bp.route('/frete', methods=['GET', 'POST'])
def config_frete():
    """Configurar frete local e frete grátis."""
    from app.models import ConfigFrete
    config = ConfigFrete.get()
    if request.method == 'POST':
        config.local_valor        = float(request.form.get('local_valor') or 15)
        local_gratis              = (request.form.get('local_gratis_acima') or '').strip()
        config.local_gratis_acima = float(local_gratis) if local_gratis else None
        fora_gratis               = (request.form.get('fora_gratis_acima') or '').strip()
        config.fora_gratis_acima  = float(fora_gratis) if fora_gratis else None
        db.session.commit()
        flash('Configurações de frete salvas!', 'success')
        return redirect(url_for('admin.config_frete'))
    return render_template('admin/frete.html', config=config)


# ==================== CONTEÚDO DO SITE ====================

@admin_bp.route('/config-site', methods=['GET', 'POST'])
def config_site():
    """Configurar imagens do site."""
    from app.models import SiteConfig
    if request.method == 'POST':
        colecao_url = (request.form.get('colecao_exclusiva_imagem') or '').strip()
        historia_url = (request.form.get('nossa_historia_imagem') or '').strip()
        SiteConfig.set('colecao_exclusiva_imagem', colecao_url or None)
        SiteConfig.set('nossa_historia_imagem', historia_url or None)
        flash('Imagens do site atualizadas!', 'success')
        return redirect(url_for('admin.config_site'))
    colecao_imagem = SiteConfig.get('colecao_exclusiva_imagem')
    historia_imagem = SiteConfig.get('nossa_historia_imagem')
    return render_template('admin/config_site.html',
                           colecao_imagem=colecao_imagem,
                           historia_imagem=historia_imagem)


# ==================== USUÁRIOS ====================

@admin_bp.route('/usuarios')
def usuarios():
    """Listar todos os usuários."""
    from sqlalchemy import func
    usuarios_lista = db.session.query(
        User,
        func.count(Order.id).label('total_pedidos')
    ).outerjoin(Order, User.id == Order.user_id).group_by(User.id).order_by(User.criado_em.desc()).all()

    return render_template('admin/usuarios.html', usuarios=usuarios_lista)


