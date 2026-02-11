"""Formulários Flask-WTF da aplicação FERRATO."""

from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField, FileAllowed
from wtforms import StringField, PasswordField, BooleanField, TextAreaField, DecimalField, IntegerField, SelectField
from wtforms.validators import DataRequired, EqualTo, Length, ValidationError, Optional, NumberRange

from app.models import User, Product, Category


class LoginForm(FlaskForm):
    """Formulário de login."""

    email = StringField('Email', validators=[
        DataRequired(message='Email é obrigatório')
    ])
    senha = PasswordField('Senha', validators=[
        DataRequired(message='Senha é obrigatória')
    ])
    lembrar = BooleanField('Lembrar-me')


class RegistroForm(FlaskForm):
    """Formulário de registro de usuário."""

    nome = StringField('Nome Completo', validators=[
        DataRequired(message='Nome é obrigatório'),
        Length(min=3, max=100, message='Nome deve ter entre 3 e 100 caracteres')
    ])
    email = StringField('Email', validators=[
        DataRequired(message='Email é obrigatório')
    ])
    senha = PasswordField('Senha', validators=[
        DataRequired(message='Senha é obrigatória'),
        Length(min=6, message='Senha deve ter no mínimo 6 caracteres')
    ])
    confirmar_senha = PasswordField('Confirmar Senha', validators=[
        DataRequired(message='Confirmação de senha é obrigatória'),
        EqualTo('senha', message='As senhas devem ser iguais')
    ])

    def validate_email(self, field):
        """Valida se o email já está cadastrado."""
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('Este email já está cadastrado.')


class ProductForm(FlaskForm):
    """Formulário de produto para admin."""

    nome = StringField('Nome do Produto', validators=[
        DataRequired(message='Nome é obrigatório'),
        Length(max=150, message='Nome muito longo')
    ])

    slug = StringField('Slug (URL)', validators=[
        Length(max=150, message='Slug muito longo')
    ])

    descricao = TextAreaField('Descrição', validators=[
        Optional()
    ])

    preco = DecimalField('Preço (R$)', validators=[
        DataRequired(message='Preço é obrigatório'),
        NumberRange(min=0.01, message='Preço deve ser maior que zero')
    ], places=2)

    preco_promocional = DecimalField('Preço Promocional (R$)', validators=[
        Optional(),
        NumberRange(min=0.01, message='Preço promocional inválido')
    ], places=2)

    imagem_url = StringField('URL da Imagem', validators=[
        Optional(),
        Length(max=300)
    ])

    imagens = MultipleFileField('Imagens do Produto', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Apenas imagens são permitidas!')
    ])

    categoria_id = SelectField('Categoria', validators=[
        DataRequired(message='Categoria é obrigatória')
    ], coerce=int)

    destaque = BooleanField('Produto em Destaque')
    novo = BooleanField('Produto Novo')
    ativo = BooleanField('Produto Ativo', default=True)

    def __init__(self, produto_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Popular dropdown de categorias
        self.categoria_id.choices = [
            (cat.id, cat.nome) for cat in Category.query.order_by(Category.nome).all()
        ]
        self.produto_id = produto_id

    def validate_slug(self, field):
        """Valida se o slug é único."""
        if field.data:
            query = Product.query.filter_by(slug=field.data)
            if self.produto_id:
                query = query.filter(Product.id != self.produto_id)
            if query.first():
                raise ValidationError('Este slug já está em uso.')

    def validate_preco_promocional(self, field):
        """Valida se preço promocional é menor que preço base."""
        if field.data and self.preco.data:
            if field.data >= self.preco.data:
                raise ValidationError('Preço promocional deve ser menor que o preço base.')


class CheckoutForm(FlaskForm):
    """Formulário de checkout para finalização de compra."""

    # Dados pessoais
    nome = StringField('Nome Completo', validators=[
        DataRequired(message='Nome é obrigatório'),
        Length(min=3, max=100, message='Nome deve ter entre 3 e 100 caracteres')
    ])
    email = StringField('Email', validators=[
        DataRequired(message='Email é obrigatório')
    ])
    telefone = StringField('Telefone', validators=[
        DataRequired(message='Telefone é obrigatório'),
        Length(min=10, max=20, message='Telefone inválido')
    ])

    # Endereço de entrega
    cep = StringField('CEP', validators=[
        DataRequired(message='CEP é obrigatório'),
        Length(min=8, max=9, message='CEP inválido')
    ])
    endereco = StringField('Endereço', validators=[
        DataRequired(message='Endereço é obrigatório'),
        Length(max=200, message='Endereço muito longo')
    ])
    numero = StringField('Número', validators=[
        DataRequired(message='Número é obrigatório'),
        Length(max=20, message='Número muito longo')
    ])
    complemento = StringField('Complemento', validators=[
        Optional(),
        Length(max=100, message='Complemento muito longo')
    ])
    bairro = StringField('Bairro', validators=[
        DataRequired(message='Bairro é obrigatório'),
        Length(max=100, message='Bairro muito longo')
    ])
    cidade = StringField('Cidade', validators=[
        DataRequired(message='Cidade é obrigatória'),
        Length(max=100, message='Cidade muito longa')
    ])
    estado = SelectField('Estado', validators=[
        DataRequired(message='Estado é obrigatório')
    ], choices=[
        ('AC', 'Acre'), ('AL', 'Alagoas'), ('AP', 'Amapá'), ('AM', 'Amazonas'),
        ('BA', 'Bahia'), ('CE', 'Ceará'), ('DF', 'Distrito Federal'), ('ES', 'Espírito Santo'),
        ('GO', 'Goiás'), ('MA', 'Maranhão'), ('MT', 'Mato Grosso'), ('MS', 'Mato Grosso do Sul'),
        ('MG', 'Minas Gerais'), ('PA', 'Pará'), ('PB', 'Paraíba'), ('PR', 'Paraná'),
        ('PE', 'Pernambuco'), ('PI', 'Piauí'), ('RJ', 'Rio de Janeiro'), ('RN', 'Rio Grande do Norte'),
        ('RS', 'Rio Grande do Sul'), ('RO', 'Rondônia'), ('RR', 'Roraima'), ('SC', 'Santa Catarina'),
        ('SP', 'São Paulo'), ('SE', 'Sergipe'), ('TO', 'Tocantins')
    ])
