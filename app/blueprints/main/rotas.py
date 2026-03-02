"""Rotas do blueprint principal."""

import logging

from flask import render_template, send_file, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from io import BytesIO
from app.blueprints.main import main_bp
from app.models import CartItem, Category, Cupom, Product, ProductImage, Order, Wishlist, SiteConfig
from app.forms import EditarPerfilForm
from app import db

logger = logging.getLogger(__name__)


@main_bp.route('/')
def home():
    """Página inicial."""
    categorias = Category.query.all()
    destaques = Product.query.filter_by(destaque=True, ativo=True).limit(4).all()
    colecao_imagem = SiteConfig.get('colecao_exclusiva_imagem')
    historia_imagem = SiteConfig.get('nossa_historia_imagem')
    return render_template('main/home.html', categorias=categorias, destaques=destaques,
                           colecao_imagem=colecao_imagem, historia_imagem=historia_imagem)


@main_bp.route('/conta/pedidos')
@login_required
def meus_pedidos():
    """Lista de pedidos do usuário logado."""
    from app.blueprints.cart import mercadopago_service

    pedidos = Order.query.filter_by(user_id=current_user.id).order_by(Order.criado_em.desc()).all()

    # Reconciliação lazy: confirmar pagamentos pendentes consultando o MP
    for pedido in pedidos:
        if pedido.status == 'aguardando_pagamento' and pedido.mercadopago_preference_id:
            try:
                resultado = mercadopago_service.consultar_pagamento(pedido.mercadopago_preference_id)
                if resultado and resultado['status'] == 'approved' and resultado.get('payment_id'):
                    for item in pedido.items:
                        if item.variant:
                            item.variant.estoque -= item.quantidade
                        else:
                            item.product.estoque -= item.quantidade
                    pedido.status = 'pago'
                    pedido.mercadopago_payment_id = resultado['payment_id']
                    CartItem.query.filter_by(user_id=current_user.id).delete()
                    if pedido.cupom_codigo:
                        cupom = Cupom.query.filter_by(codigo=pedido.cupom_codigo).first()
                        if cupom:
                            cupom.usos_atuais += 1
                    db.session.commit()
                    try:
                        from app.blueprints.cart.email_pedido_service import enviar_email_pedido_confirmado
                        enviar_email_pedido_confirmado(pedido)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning('[PEDIDOS] Erro ao verificar pedido #%s: %s', pedido.id, e)

    return render_template('conta/pedidos.html', pedidos=pedidos)


@main_bp.route('/conta/pedidos/<int:id>')
@login_required
def meu_pedido_detalhe(id):
    """Detalhe de um pedido do usuário logado."""
    pedido = Order.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    return render_template('conta/pedido_detalhe.html', pedido=pedido)


@main_bp.route('/conta/favoritos/toggle', methods=['POST'])
@login_required
def toggle_favorito():
    """Adicionar/remover produto dos favoritos (AJAX)."""
    from flask import request, jsonify
    product_id = request.json.get('product_id')
    if not product_id:
        return jsonify(erro='product_id obrigatório'), 400

    produto = Product.query.get_or_404(product_id)
    existente = Wishlist.query.filter_by(user_id=current_user.id, product_id=produto.id).first()

    if existente:
        db.session.delete(existente)
        db.session.commit()
        return jsonify(favoritado=False)
    else:
        fav = Wishlist(user_id=current_user.id, product_id=produto.id)
        db.session.add(fav)
        db.session.commit()
        return jsonify(favoritado=True)


@main_bp.route('/conta/favoritos')
@login_required
def meus_favoritos():
    """Lista de produtos favoritos do usuário."""
    favoritos = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.criado_em.desc()).all()
    return render_template('conta/favoritos.html', favoritos=favoritos)


@main_bp.route('/conta/perfil', methods=['GET', 'POST'])
@login_required
def meu_perfil():
    """Página de edição do perfil do usuário."""
    form = EditarPerfilForm(obj=current_user)
    if form.validate_on_submit():
        current_user.nome = form.nome.data.strip()

        if form.senha_atual.data:
            if not current_user.check_senha(form.senha_atual.data):
                flash('Senha atual incorreta.', 'error')
                return render_template('conta/perfil.html', form=form)
            if not form.nova_senha.data:
                flash('Informe a nova senha.', 'error')
                return render_template('conta/perfil.html', form=form)
            current_user.set_senha(form.nova_senha.data)
            from app.models import PasswordResetToken
            PasswordResetToken.query.filter_by(
                email=current_user.email, usado=False
            ).update({'usado': True})

        db.session.commit()
        flash('Perfil atualizado com sucesso.', 'success')
        return redirect(url_for('main.meu_perfil'))

    return render_template('conta/perfil.html', form=form)


@main_bp.route('/sobre')
def sobre():
    return render_template('institucional/sobre.html')


@main_bp.route('/trocas-e-devolucoes')
def trocas_devolucoes():
    return render_template('institucional/trocas.html')


@main_bp.route('/privacidade')
def privacidade():
    return render_template('institucional/privacidade.html')


@main_bp.route('/termos')
def termos():
    return render_template('institucional/termos.html')


@main_bp.route('/produto/imagem/<int:image_id>')
def servir_imagem(image_id):
    """Serve uma imagem de produto armazenada no banco de dados."""
    imagem = ProductImage.query.get_or_404(image_id)
    return send_file(
        BytesIO(imagem.data),
        mimetype=imagem.mimetype,
        as_attachment=False,
        download_name=imagem.filename
    )
