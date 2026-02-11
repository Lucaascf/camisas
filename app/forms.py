"""Formulários Flask-WTF da aplicação FERRATO."""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, EmailField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.models import User


class LoginForm(FlaskForm):
    """Formulário de login."""

    email = EmailField('Email', validators=[
        DataRequired(message='Email é obrigatório'),
        Email(message='Email inválido')
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
    email = EmailField('Email', validators=[
        DataRequired(message='Email é obrigatório'),
        Email(message='Email inválido')
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
