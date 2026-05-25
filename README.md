# EquipAV — Controle de Equipamentos Audiovisuais

Sistema interno para controle de entrada e saída de equipamentos audiovisuais
em coberturas e reportagens externas.

## Funcionalidades

- Registro de saída de equipamentos por pauta (viagem)
- Campos: pauta, período, cinegrafista, repórter, destino, equipamentos, observações
- Upload de foto na saída e na devolução (armazenamento em Cloudflare R2)
- Dashboard com filtros: em campo / devolvidos
- Área administrativa para configuração do armazenamento

## Stack

- Python 3.12 + Flask
- SQLite (banco local persistente)
- Cloudflare R2 para fotos
- Bootstrap 5

## Rodando localmente

```bash
pip install -r requirements.txt
python app.py
```

App fica disponível em `http://localhost:5001`.

## Variáveis de ambiente (opcionais)

| Variável | Descrição |
|---|---|
| `PORT` | Porta do servidor (default: 5001) |
| `DATA_DIR` | Onde salva o banco e a config (default: `./data`) |
| `ADMIN_KEY` | Chave de acesso a `/admin` (default: `equipav2024`) |
| `SECRET_KEY` | Chave de sessão do Flask |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL`, `R2_PREFIX` | Credenciais R2 (alternativa ao painel admin) |

## Configurando o R2

1. Crie um bucket no Cloudflare R2
2. Gere um API Token com permissão **Object Read & Write**
3. Habilite **R2.dev subdomain** (ou conecte um domínio custom)
4. Acesse `/admin` no app e cole as credenciais
