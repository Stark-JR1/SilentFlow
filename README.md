# 💰 FinTrack Pro — Python Edition

App de finanças pessoais e familiares em Python.
**Stack:** FastAPI + Jinja2 + Supabase/PostgreSQL + Chart.js

---

## Stack Completa

| Camada       | Tecnologia                         |
|--------------|------------------------------------|
| Backend      | FastAPI 0.111 + Uvicorn            |
| Templates    | Jinja2 (server-side rendering)     |
| Frontend     | HTML/CSS/JS puro + Chart.js        |
| Banco        | Supabase (PostgreSQL)              |
| Auth         | Supabase Auth (sessão via cookie)  |
| Validação    | Pydantic v2                        |
| Deploy       | Render (ou qualquer VPS)           |

---

## Estrutura de Pastas

```
fintrack-python/
├── main.py                         # Entry point FastAPI
├── requirements.txt
├── .env.example
├── app/
│   ├── core/
│   │   ├── config.py               # Settings / variáveis de ambiente
│   │   └── supabase.py             # Clientes Supabase + dependências de auth
│   ├── routers/
│   │   ├── auth.py                 # Login, registro, logout, reset
│   │   ├── pages.py                # Rotas que retornam HTML (GET)
│   │   └── api.py                  # Rotas JSON para chamadas AJAX
│   ├── services/
│   │   └── db.py                   # Camada de dados — todas as queries Supabase
│   ├── schemas/
│   │   └── models.py               # Pydantic schemas, enums, payloads
│   └── utils/
│       └── helpers.py              # Formatação, KPIs, insights, datas
├── templates/
│   ├── base.html                   # Layout base com sidebar + modal global
│   ├── auth/
│   │   ├── login.html
│   │   ├── register.html
│   │   └── reset.html
│   └── pages/
│       ├── dashboard.html
│       ├── transactions.html
│       ├── accounts.html
│       ├── cards.html
│       ├── goals.html
│       ├── recurring.html
│       ├── reports.html
│       ├── family.html
│       ├── alerts.html
│       └── 404.html
├── static/
│   ├── css/                        # CSS extra (opcional)
│   └── js/                         # JS extra (opcional)
└── supabase/
    ├── migrations/
    │   └── 001_initial_schema.sql  # Schema completo + RLS + triggers
    └── seeds/
        └── 001_categories.sql      # Categorias padrão
```

---

## Como Rodar Localmente

### Pré-requisitos
- Python 3.11+
- Conta no Supabase (gratuita)

### 1. Clonar e criar ambiente virtual

```bash
git clone https://github.com/seu-usuario/fintrack-python
cd fintrack-python

python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env` com suas credenciais do Supabase:

```env
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_ANON_KEY=sua-anon-key
SUPABASE_SERVICE_ROLE_KEY=sua-service-role-key
APP_SECRET_KEY=minimo-32-caracteres-aleatorios
JWT_SECRET_KEY=outro-secret-aleatorio
```

### 3. Configurar banco de dados

No painel do Supabase → **SQL Editor**, execute em ordem:

```
1. supabase/migrations/001_initial_schema.sql
2. supabase/seeds/001_categories.sql
```

### 4. Rodar

```bash
python main.py
# ou
uvicorn main:app --reload --port 8000
```

Acesse: **http://localhost:8000**

---

## Como Configurar o Supabase

1. Acesse [supabase.com](https://supabase.com) → New Project
2. Copie **Project URL** e **anon key** em Settings > API
3. Copie **service_role key** em Settings > API > Project API keys
4. Execute os SQLs conforme acima
5. Em **Authentication > URL Configuration**, adicione `http://localhost:8000` como Site URL
6. Em **Authentication > Email Templates**, configure os templates de email (opcional)

---

## Deploy no Render

1. Crie conta em [render.com](https://render.com)
2. **New Web Service** → conecte seu repositório
3. Configurações:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Adicione as variáveis de ambiente do `.env.example`
5. Defina `APP_ENV=production`
6. Deploy!

---

## Variáveis de Ambiente

| Variável                    | Descrição                          | Obrigatório |
|-----------------------------|------------------------------------|-------------|
| `SUPABASE_URL`              | URL do projeto Supabase            | ✅          |
| `SUPABASE_ANON_KEY`         | Chave anônima pública              | ✅          |
| `SUPABASE_SERVICE_ROLE_KEY` | Chave service role (server-only)   | ✅          |
| `APP_SECRET_KEY`            | Secret para cookies de sessão      | ✅          |
| `APP_ENV`                   | `development` ou `production`      | ✅          |
| `APP_PORT`                  | Porta (default: 8000)              | ❌          |
| `JWT_SECRET_KEY`            | Secret JWT                         | ✅          |

---

## Arquitetura de Segurança

- **RLS ativo** no Supabase — banco bloqueia acesso indevido mesmo se API falhar
- **SessionMiddleware** com cookie httpOnly para autenticação
- **Pydantic v2** valida todos os payloads de entrada
- **Soft delete** em transações, contas, cartões e metas
- **Isolamento** por `user_id` em todas as queries
- **Service role** nunca exposta ao cliente

---

## Endpoints Disponíveis

### Páginas (HTML)
```
GET  /                    → Redirect para /dashboard ou /auth/login
GET  /dashboard
GET  /transactions
GET  /accounts
GET  /cards
GET  /goals
GET  /recurring
GET  /reports
GET  /family
GET  /alerts
GET  /auth/login
GET  /auth/register
GET  /auth/reset-password
```

### Auth
```
POST /auth/login
POST /auth/register
POST /auth/reset-password
GET  /auth/logout
```

### API JSON
```
GET/POST   /api/transactions
PATCH/DEL  /api/transactions/{id}
GET/POST   /api/accounts
GET/POST   /api/cards
GET/POST   /api/goals
POST       /api/goals/{id}/contribute
GET/POST   /api/recurring
GET/POST   /api/family
GET        /api/categories
GET        /api/dashboard
PATCH      /api/notifications/{id}/read
```

Documentação interativa disponível em `/docs` (apenas em `APP_ENV=development`).

---

## Próximos Passos

- [ ] Background task para gerar recorrentes automaticamente (APScheduler)
- [ ] Export de relatório em PDF (WeasyPrint ou ReportLab)
- [ ] Import de extrato OFX/CSV
- [ ] Notificações push via WebSocket
- [ ] Módulo de IA para categorização automática (integração com API externa)

---

MIT License
