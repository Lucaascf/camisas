"""Ponto de entrada da aplicação FERRATO."""

from app import criar_app

app = criar_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
