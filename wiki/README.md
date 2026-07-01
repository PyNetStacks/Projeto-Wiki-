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

## Deploy no Railway

1. Suba este repositório no GitHub.
2. No Railway: **New Project → Deploy from GitHub repo**.
3. Configure as variáveis de ambiente (aba Variables):
   - `WIKI_SECRET_KEY` = uma string aleatória longa
   - `FLASK_DEBUG` = `0`
   - `DATA_DIR` = `/data`
4. Crie um **Volume** (aba Volumes) e monte em `/data` — isso mantém o banco de dados
   salvo entre deploys (sem isso, o conteúdo da wiki seria apagado a cada novo deploy).
5. Gere o domínio público na aba Settings → Networking.
6. Acesse o site, faça login e troque a senha do admin.

## Estrutura

- `app.py` — aplicação Flask completa (rotas, templates, banco de dados)
- `requirements.txt` — dependências Python
- `Procfile` — comando de start usado pelo Railway (gunicorn)
- `runtime.txt` — versão do Python
- `.gitignore` — ignora banco local e arquivos temporários
