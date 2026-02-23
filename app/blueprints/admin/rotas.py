"""Rotas do painel administrativo."""

import logging
import re
from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps

from app import db
from app.blueprints.admin import admin_bp
from app.forms import ProductForm, CategoryForm
from app.models import Cupom, Product, Category, ProductImage, ProductImageURL, ProductVariant, Order, User

logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator para verificar se usuário é admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Faça login para acessar o painel admin.', 'error')
            return redirect(url_for('auth.login'))
        if not current_user.admin:
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated_function


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

    return render_template(
        'admin/dashboard.html',
        produtos=produtos,
        total_pedidos=total_pedidos,
        pedidos_pendentes=pedidos_pendentes,
        receita_total=receita_total,
        total_usuarios=total_usuarios,
        estoque_baixo=estoque_baixo,
    )


@admin_bp.route('/pedidos')
def pedidos():
    """Listar todos os pedidos com filtro por status."""
    status_filtro = request.args.get('status', '')
    query = Order.query.order_by(Order.criado_em.desc())
    if status_filtro:
        query = query.filter_by(status=status_filtro)
    pedidos = query.all()
    return render_template('admin/pedidos.html', pedidos=pedidos, status_filtro=status_filtro)


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
@admin_required
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
        flash(f'Erro ao consultar MP: {e}', 'error')

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
                    print(f"DEBUG: Adicionando arquivo {idx}: {arquivo.filename}")
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

    return render_template('admin/produto_form.html', form=form, produto=produto)


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
    """Salvar/atualizar variantes (tamanhos) de um produto."""
    produto = Product.query.get_or_404(id)

    dados = request.get_json()
    if not dados or 'variantes' not in dados:
        return jsonify(sucesso=False, mensagem='Dados inválidos'), 400

    variantes_dados = dados['variantes']
    variantes_criadas = []

    try:
        for v_data in variantes_dados:
            tamanho = v_data.get('tamanho')
            ativo = v_data.get('ativo', False)
            estoque = v_data.get('estoque', 0)
            variant_id = v_data.get('id')

            if variant_id:
                # Atualizar variante existente
                variante = ProductVariant.query.get(variant_id)
                if variante and variante.product_id == produto.id:
                    variante.ativo = ativo
                    variante.estoque = estoque if ativo else 0
                    variantes_criadas.append({
                        'id': variante.id,
                        'tamanho': variante.tamanho,
                        'estoque': variante.estoque,
                        'ativo': variante.ativo
                    })
            else:
                # Buscar se já existe variante para esse tamanho
                variante = ProductVariant.query.filter_by(
                    product_id=produto.id,
                    tamanho=tamanho
                ).first()

                if variante:
                    # Atualizar existente
                    variante.ativo = ativo
                    variante.estoque = estoque if ativo else 0
                else:
                    # Criar nova variante apenas se estiver ativa
                    if ativo:
                        variante = ProductVariant(
                            product_id=produto.id,
                            tamanho=tamanho,
                            estoque=estoque,
                            ativo=True
                        )
                        db.session.add(variante)
                        db.session.flush()  # Para obter o ID

                if variante:
                    variantes_criadas.append({
                        'id': variante.id,
                        'tamanho': variante.tamanho,
                        'estoque': variante.estoque,
                        'ativo': variante.ativo
                    })

        db.session.commit()

        return jsonify(
            sucesso=True,
            mensagem='Variantes salvas com sucesso!',
            variantes=variantes_criadas
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(sucesso=False, mensagem=str(e)), 500


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
            slug = re.sub(r'[^\w\s-]', '', form.nome.data.lower())
            slug = slug.replace(' ', '-')

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
            slug = re.sub(r'[^\w\s-]', '', form.nome.data.lower())
            slug = slug.replace(' ', '-')

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


