from app import create_app

# Inicializa a aplicação
app = create_app()

if __name__ == "__main__":
    print("--- INICIANDO SERVIDOR DE DESENVOLVIMENTO (Porta 5001) ---")
    app.run(host='0.0.0.0', port=5001, debug=True)
