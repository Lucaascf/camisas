"""Rotas do painel administrativo."""

import re
from flask import render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from functools import wraps

from app import db
from app.blueprints.admin import admin_bp
from app.forms import ProductForm
from app.models import Product, Category, ProductImage, ProductVariant, Order


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
    """Dashboard admin com lista de produtos."""
    produtos = Product.query.order_by(Product.criado_em.desc()).all()
    return render_template('admin/dashboard.html', produtos=produtos)


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
    flash(f'Status do pedido #{pedido.id} atualizado para "{novo_status}".', 'success')
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
