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
    imagem_data = db.Column(db.LargeBinary, nullable=True)
    imagem_mimetype = db.Column(db.String(50), nullable=True)

    products = db.relationship('Product', backref='categoria', lazy=True)

    @property
    def imagem_principal(self):
        if self.imagem_data:
            return f'/categoria/imagem/{self.id}'
        return self.imagem_url or None

    def __repr__(self):
        return f'<Category {self.nome}>'


class Marca(db.Model):
    """Marca de produto."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    products = db.relationship('Product', backref='marca', lazy=True)

    def __repr__(self):
        return f'<Marca {self.nome}>'


class Tecido(db.Model):
    """Tipo de tecido de produto."""

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    products = db.relationship('Product', backref='tecido', lazy=True)

    def __repr__(self):
        return f'<Tecido {self.nome}>'


PIX_DESCONTO = 0.05  # 5% de desconto no PIX


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
    marca_id = db.Column(db.Integer, db.ForeignKey('marca.id'), nullable=True)
    tecido_id = db.Column(db.Integer, db.ForeignKey('tecido.id'), nullable=True)
    destaque = db.Column(db.Boolean, default=False)
    novo = db.Column(db.Boolean, default=False)
    ativo = db.Column(db.Boolean, default=True)
    estoque = db.Column(db.Integer, default=0)  # Mantido para produtos antigos, mas variantes têm seu próprio estoque
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def preco_final(self):
        return self.preco_promocional if self.preco_promocional else self.preco

    @property
    def preco_pix(self):
        """Preço com desconto PIX (5% sobre o preço final)."""
        return round(self.preco_final * (1 - PIX_DESCONTO), 2)

    @property
    def em_promocao(self):
        return self.preco_promocional is not None

    @property
    def percentual_desconto(self):
        if not self.em_promocao:
            return 0
        return round((1 - self.preco_promocional / self.preco) * 100)

    @property
    def todas_imagens(self):
        """Retorna todas as imagens (binárias + URL), ordenadas por `ordem`."""
        todas = list(self.imagens) + list(self.imagens_url)
        return sorted(todas, key=lambda x: x.ordem)

    @property
    def imagem_principal(self):
        """Retorna a URL da imagem principal do produto."""
        todas = self.todas_imagens
        if todas:
            return todas[0].src
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
    """Variante de produto (tamanho + cor)."""

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    tamanho = db.Column(db.String(10), nullable=False, server_default='')
    cor = db.Column(db.String(50), nullable=False, server_default='')
    cor_hex = db.Column(db.String(7), nullable=False, server_default='')
    estoque = db.Column(db.Integer, default=0, nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product', backref='variantes', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('product_id', 'tamanho', 'cor', name='uq_product_variant'),
    )

    def __repr__(self):
        return f'<ProductVariant {self.product_id} - {self.tamanho} {self.cor}>'


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

    # Mercado Pago
    mercadopago_preference_id = db.Column(db.String(200), nullable=True)
    mercadopago_payment_id = db.Column(db.String(200), nullable=True)
    pix_qr_code = db.Column(db.Text, nullable=True)
    pix_qr_code_base64 = db.Column(db.Text, nullable=True)

    # Frete
    frete_tipo  = db.Column(db.String(60), nullable=True)
    frete_valor = db.Column(db.Float, default=0.0)

    # Cupom de desconto
    cupom_codigo   = db.Column(db.String(20), nullable=True)
    desconto_valor = db.Column(db.Float, default=0.0)

    # Logística
    codigo_rastreio = db.Column(db.String(100), nullable=True)
    codigo_cliente = db.Column(db.String(15), unique=True, nullable=True)

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
    cor = db.Column(db.String(50), nullable=True)      # Snapshot da cor no momento da compra
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Float, nullable=False)

    product = db.relationship('Product', backref='order_items', lazy=True)
    variant = db.relationship('ProductVariant', backref='order_items', lazy=True)

    def __repr__(self):
        return f'<OrderItem order={self.order_id} product={self.product_id} variant={self.variant_id}>'


class PasswordResetToken(db.Model):
    """Token de redefinição de senha."""

    __tablename__ = 'password_reset_token'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    token = db.Column(db.String(64), nullable=False, unique=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expira_em = db.Column(db.DateTime, nullable=False)
    usado = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<PasswordResetToken {self.email}>'


class Wishlist(db.Model):
    """Lista de desejos do usuário."""

    __tablename__ = 'wishlist'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='wishlist_items', lazy=True)
    product = db.relationship('Product', backref='wishlist_items', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'product_id', name='uq_wishlist_user_product'),
    )

    def __repr__(self):
        return f'<Wishlist user={self.user_id} product={self.product_id}>'


class Cupom(db.Model):
    """Cupom de desconto."""

    __tablename__ = 'cupom'

    id                  = db.Column(db.Integer, primary_key=True)
    codigo              = db.Column(db.String(20), unique=True, nullable=False)
    desconto_percentual = db.Column(db.Float, nullable=False)   # ex: 15.0 = 15%
    ativo               = db.Column(db.Boolean, default=True)
    validade            = db.Column(db.DateTime, nullable=True)  # None = sem prazo
    usos_maximos        = db.Column(db.Integer, nullable=True)   # None = ilimitado
    usos_atuais         = db.Column(db.Integer, default=0)
    criado_em           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Cupom {self.codigo} {self.desconto_percentual}%>'


class ProductImage(db.Model):
    """Imagem de produto armazenada no banco de dados."""

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(50), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    ordem = db.Column(db.Integer, default=0)
    cor = db.Column(db.String(50), nullable=False, server_default='')
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship('Product', backref='imagens', lazy=True)

    @property
    def src(self):
        return f'/produto/imagem/{self.id}'

    def __repr__(self):
        return f'<ProductImage {self.filename} for product {self.product_id}>'


class ProductImageURL(db.Model):
    """Imagem de produto via URL externa."""

    __tablename__ = 'product_image_url'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    ordem = db.Column(db.Integer, default=0)
    cor = db.Column(db.String(50), nullable=False, server_default='')
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    produto = db.relationship('Product', backref='imagens_url', lazy=True)

    @property
    def src(self):
        return self.url

    def __repr__(self):
        return f'<ProductImageURL {self.url[:50]} for product {self.product_id}>'


class ConfigFrete(db.Model):
    """Configuração de frete da loja (singleton — id=1)."""
    __tablename__ = 'config_frete'

    id = db.Column(db.Integer, primary_key=True)

    # Salvador / Lauro de Freitas
    local_valor        = db.Column(db.Float, default=15.0)   # frete fixo em R$
    local_gratis_acima = db.Column(db.Float, nullable=True)  # None = sem frete grátis

    # Fora de Salvador/LF (Melhor Envio) — apenas limiar de grátis
    fora_gratis_acima  = db.Column(db.Float, nullable=True)  # None = sem frete grátis

    @classmethod
    def get(cls):
        config = cls.query.first()
        if not config:
            config = cls(id=1)
            db.session.add(config)
            db.session.commit()
        return config


class SiteConfig(db.Model):
    """Configurações genéricas do site (chave-valor)."""

    __tablename__ = 'site_config'

    chave = db.Column(db.Text, primary_key=True)
    valor = db.Column(db.Text, nullable=True)

    @classmethod
    def get(cls, chave, default=None):
        row = cls.query.filter_by(chave=chave).first()
        return row.valor if row else default

    @classmethod
    def set(cls, chave, valor):
        row = cls.query.filter_by(chave=chave).first()
        if row:
            row.valor = valor
        else:
            db.session.add(cls(chave=chave, valor=valor))
        db.session.commit()


class EnderecoSalvo(db.Model):
    """Endereço de entrega salvo pelo usuário."""

    __tablename__ = 'endereco_salvo'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    apelido     = db.Column(db.String(50), nullable=True)
    cep         = db.Column(db.String(9), nullable=False)
    endereco    = db.Column(db.String(200), nullable=False)
    numero      = db.Column(db.String(20), nullable=False)
    complemento = db.Column(db.String(100), nullable=True)
    bairro      = db.Column(db.String(100), nullable=False)
    cidade      = db.Column(db.String(100), nullable=False)
    estado      = db.Column(db.String(2), nullable=False)
    criado_em   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='enderecos_salvos', lazy=True)
