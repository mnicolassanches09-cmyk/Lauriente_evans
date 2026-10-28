# Laurient Evans — Gestão Hospitalar

Sistema web (projeto acadêmico, **dados 100% fictícios**) para agendamento de consultas, feito com
Python 3 + Flask, SQLite, HTML5/CSS3, Jinja2, Flask-Login e Flask-WTF (CSRF).

> Não é um sistema certificado nem pronto para uso clínico real: exigiria auditoria de segurança,
> avaliação de privacidade (LGPD) e testes adicionais.

## Como executar (Windows / PowerShell)

```powershell
# 1. Entrar na pasta do projeto
cd laurient_evans

# 2. Criar e ativar o ambiente virtual
python -m venv venv
venv\Scripts\Activate.ps1          # (no CMD: venv\Scripts\activate.bat)
# Linux/macOS: python3 -m venv venv && source venv/bin/activate

# 3. Instalar as dependências
pip install -r requirements.txt

# 4. Variáveis de ambiente (PowerShell). Gere uma chave: python -c "import secrets; print(secrets.token_hex(32))"
$env:SECRET_KEY = "cole-a-chave-gerada-aqui"
# Linux/macOS: export SECRET_KEY="..."

# 5. Criar o banco + médicos e especialidades fictícios
flask --app app init-db

# 6. Criar o primeiro administrador (a senha é digitada, nunca fica no código)
python scripts/create_admin.py

# 7. Rodar o servidor (apenas desenvolvimento)
flask --app app run

# 8. Acessar
#   Site:       http://127.0.0.1:5000
#   Secretaria: http://127.0.0.1:5000/admin/entrar

# 9. Testes automatizados (usam banco temporário, separado do de demonstração)
python -m pytest
```

Se o PowerShell bloquear a ativação do venv:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Os ícones usam Font Awesome via CDN (precisa de internet; sem ela o site funciona, só sem os ícones).

Variáveis opcionais: `CANCEL_MIN_HOURS` (antecedência mínima para cancelar, padrão 2; `0` = sem restrição),
`DATABASE_PATH`, `SESSION_COOKIE_SECURE=1` (quando houver HTTPS).

## Arquitetura

| Arquivo | Função |
|---|---|
| `app.py` | Fábrica `create_app`, erros 403/404/500, cabeçalhos de segurança, comando `flask init-db` |
| `config.py` | Configurações (chave secreta por variável de ambiente, política de cancelamento, cookies) |
| `extensions.py` | Flask-Login e proteção CSRF |
| `models.py` | Schema SQLite, usuário, **regras de agenda** (`available_slots`, `book_appointment`), dados de demonstração |
| `utils.py` | Validação de CPF, decorador de papéis, auditoria, filtros de template |
| `routes/auth.py` | Páginas públicas, cadastro, login de paciente e de administrador, logout |
| `routes/patient.py` | Painel e dados cadastrais do paciente |
| `routes/appointments.py` | Fluxo de agendamento, detalhes e cancelamento |
| `routes/admin.py` | Painel, consultas, médicos, especialidades, pacientes e auditoria |
| `scripts/create_admin.py` | Criação segura do primeiro administrador |
| `templates/`, `static/` | Páginas Jinja2, CSS (`style/auth/dashboard/admin`), `main.js`, logo |
| `tests/` | 32 testes pytest |

### Como o agendamento evita conflitos
1. A interface só **mostra** horários livres, mas isso não é confiável sozinho.
2. Ao confirmar, `book_appointment` abre uma transação `BEGIN IMMEDIATE` (bloqueio de escrita do SQLite),
   **recalcula** os horários livres do médico (considerando duração e sobreposição de intervalos
   `inicio < fim_existente E fim > inicio_existente`) e só então insere.
3. Duas requisições simultâneas são serializadas: a segunda vê o horário ocupado e recebe mensagem amigável.
4. Reforço no banco: índice único parcial `(doctor_id, start_at)` para consultas não canceladas.
5. Consultas canceladas ficam no histórico, mas não bloqueiam mais o horário.

### Datas e horários
Armazenados como texto ISO `YYYY-MM-DDTHH:MM` no horário local do servidor/hospital (sem fuso),
formato em que a ordem alfabética é a cronológica.

### Segurança
Senhas com hash (Werkzeug); CSRF em todos os POST; consultas parametrizadas; papéis verificados no servidor
(`patient` x `admin`, logins separados, 403 para papel errado); propriedade das consultas verificada
(outro paciente recebe 404); cadastro nunca cria administradores; logout e cancelamentos apenas por POST;
log de auditoria administrativa sem dados sensíveis; CPF mascarado na lista de pacientes da secretaria.

## Limitações conhecidas
Não há recuperação de senha, e-mails de confirmação, limite de tentativas de login nem edição de consultas
pela secretaria (apenas visualizar, concluir e cancelar). Para produção, use um servidor WSGI (ex.: waitress) com HTTPS.
