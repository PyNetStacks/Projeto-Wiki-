[README.md](https://github.com/user-attachments/files/29928727/README.md)
# Wiki da Campanha de RPG

Site de wiki em Flask com banco SQLite, feito para hospedar no Railway.

## Rodar localmente

```bash
pip install -r requirements.txt
python app.py
```

Acesse http://localhost:5000

Login admin padrão:
- usuário: `admin`
- senha: `admin123`
  
**Troque a senha assim que entrar** (menu "Trocar senha").
## Estrutura

- `app.py` — aplicação Flask completa (rotas, templates, banco de dados)
- `requirements.txt` — dependências Python
- `Procfile` — comando de start usado pelo Railway (gunicorn)
- `runtime.txt` — versão do Python
- `.gitignore` — ignora banco local e arquivos temporários
