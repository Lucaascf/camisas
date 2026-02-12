"""Models da aplicação FERRATO."""

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


class User(UserMixin, db.Model):
    """Usuário do sistema."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    admin = db.Column(db.Boolean, default=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    orders = db.relationship('Order', backref='user', lazy=True)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def __repr__(self):
        return f'<User {self.email}>'


class EmailVerificationToken(db.Model):
    """Token de verificação de email para registro de usuários."""

    __tablename__ = 'email_verification_token'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    codigo = db.Column(db.String(6), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    tentativas = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expira_em = db.Column(db.DateTime, nullable=False)
    verificado = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<EmailVerificationToken {self.email}>'


class Category(db.Model):
    """Categoria de produtos."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    descricao = db.Column(db.String(200))
    imagem_url = db.Column(db.String(300))

    products = db.relationship('Product', backref='categoria', lazy=True)

    def __repr__(self):
        return f'<Category {self.nome}>'


class Product(db.Model):
    """Produto (camisa)."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    descricao = db.Column(db.Text)
    preco = db.Column(db.Float, nullable=False)
    preco_promocional = db.Column(db.Float, nullable=True)
    imagem_url = db.Column(db.String(300))
    categoria_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    destaque = db.Column(db.Boolean, default=False)
    novo = db.Column(db.Boolean, default=False)
    ativo = db.Column(db.Boolean, default=True)
    estoque = db.Column(db.Integer, default=0)  # Mantido para produtos antigos, mas variantes têm seu próprio estoque
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def preco_final(self):
        return self.preco_promocional if self.preco_promocional else self.preco

    @property
    def em_promocao(self):
        return self.preco_promocional is not None

    @property
    def percentual_desconto(self):
        if not self.em_promocao:
            return 0
        return round((1 - self.preco_promocional / self.preco) * 100)

    @property
    def imagem_principal(self):
        """Retorna a URL da imagem principal do produto."""
        if self.imagens:
            # Se há imagens no banco, retorna a URL da primeira (ordenada)
            primeira = sorted(self.imagens, key=lambda x: x.ordem)[0]
            return f'/produto/imagem/{primeira.id}'
        # Fallback para imagem_url (compatibilidade com produtos antigos)
        return self.imagem_url

    @property
    def estoque_total(self):
        """Retorna o estoque total somando todas as variantes."""
        if self.variantes:
            return sum(v.estoque for v in self.variantes if v.ativo)
        return 0  # Produtos sem variantes = sem estoque

    @property
    def tem_variantes(self):
        """Verifica se o produto possui variantes ativas."""
        return bool(self.variantes and any(v.ativo for v in self.variantes))

    def __repr__(self):
        return f'<Product {self.nome}>'


class ProductVariant(db.Model):
    """Variante de produto (tamanho/cor)."""

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    tamanho = db.Column(db.String(10), nullable=False)  # P, M, G, GG, XG
    estoque = db.Column(db.Integer, default=0, nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product', backref='variantes', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('product_id', 'tamanho', name='uq_product_variant'),
    )

    def __repr__(self):
        return f'<ProductVariant {self.product_id} - {self.tamanho}>'


class CartItem(db.Model):
    """Item no carrinho de compras."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_id = db.Column(db.String(100), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    quantidade = db.Column(db.Integer, default=1)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product', backref='cart_items', lazy=True)
    variant = db.relationship('ProductVariant', backref='cart_items', lazy=True)
    user = db.relationship('User', backref='cart_items', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'product_id', 'variant_id', name='uq_cart_user_product_variant'),
        db.UniqueConstraint('session_id', 'product_id', 'variant_id', name='uq_cart_session_product_variant'),
    )

    def __repr__(self):
        return f'<CartItem product={self.product_id} variant={self.variant_id} qty={self.quantidade}>'


class Order(db.Model):
    """Pedido."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable para pedidos de convidados
    status = db.Column(db.String(20), default='pendente')
    total = db.Column(db.Float, nullable=False)

    # Dados do comprador (para convidados ou registrados)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(20))

    # Endereço de entrega
    endereco = db.Column(db.String(200), nullable=False)
    numero = db.Column(db.String(20), nullable=False)
    complemento = db.Column(db.String(100))
    bairro = db.Column(db.String(100), nullable=False)
    cidade = db.Column(db.String(100), nullable=False)
    estado = db.Column(db.String(2), nullable=False)
    cep = db.Column(db.String(9), nullable=False)

    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    items = db.relationship('OrderItem', backref='order', lazy=True)

    def __repr__(self):
        return f'<Order #{self.id} status={self.status}>'


class OrderItem(db.Model):
    """Item de um pedido."""

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    tamanho = db.Column(db.String(10), nullable=True)  # Snapshot do tamanho no momento da compra
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Float, nullable=False)

    product = db.relationship('Product', backref='order_items', lazy=True)
    variant = db.relationship('ProductVariant', backref='order_items', lazy=True)

    def __repr__(self):
        return f'<OrderItem order={self.order_id} product={self.product_id} variant={self.variant_id}>'


class ProductImage(db.Model):
    """Imagem de produto armazenada no banco de dados."""

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(50), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    ordem = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product', backref='imagens', lazy=True)

    def __repr__(self):
        return f'<ProductImage {self.filename} for product {self.product_id}>'
