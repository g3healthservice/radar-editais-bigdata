# Radar de Editais — Big Data · Gestão em Saúde (PNCP)

Automação que varre o [PNCP](https://pncp.gov.br) (Portal Nacional de Contratações Públicas) em busca de
contratações com proposta em aberto aderentes às frentes de atuação da **Big Data (gestão em saúde)**,
em todo o Brasil (esferas federal, estadual e municipal). Cada edital captado é etiquetado com o(s)
eixo(s)/CNAE que casou, com a categoria (disputar/monitorar) e com um destaque para as três frentes
prioritárias.

- Dashboard: https://g3healthservice.github.io/radar-editais-engenharia/
- Roda a cada 2h via GitHub Actions (`.github/workflows/radar-editais.yml`)
- Envia e-mail com os editais novos desde a última execução (só quando há novidade)

## Frentes captadas (por bloco de CNAE)

| CNAE | Eixo | Exemplos de palavra-chave |
|------|------|---------------------------|
| 86.60-7/00 | Apoio à gestão de saúde (eixo principal) | sistema/plataforma de gestão em saúde, gestão de leitos, regulação ambulatorial, prontuário eletrônico |
| 62.02 / 62.03 / 63.11 | Licenciamento de software / SaaS | licença de uso de sistema, sistema informatizado, software como serviço (SaaS), plataforma web |
| 78.30-2/00 | Gestão de RH / escalas e ponto | gestão de escalas, ponto eletrônico, dimensionamento de pessoal, folha e frequência |
| 86.50-0/03 | Psicologia / riscos psicossociais | riscos psicossociais (NR-1), gerenciamento de riscos ocupacionais, saúde ocupacional, QVT |
| 70.20-4/00 · 82.11-3/00 | Consultoria / apoio administrativo | canal de denúncias / ouvidoria, programa de integridade (compliance), gestão de contratos (software) |
| 66.21-5/02 | Auditoria / consultoria atuarial | avaliação atuarial, cálculo atuarial RPPS, consultoria atuarial previdência |
| 86.30-5/03 · 86.50 | Assistencial / telessaúde | telessaúde, telemedicina, teleconsulta |
| — | **Monitorar** (operadoras/planos) | gestão de plano de saúde, autogestão em saúde, auditoria de contas médicas |

⭐ **Prioritários (as três de segunda-feira):** sistema de gestão em saúde · gestão de escalas e ponto
eletrônico · riscos psicossociais NR-1.

A taxonomia fica em `pipeline/buscar_editais.py` (constante `TAXONOMIA`) — é só editar/estender lá.

## Modos de execução

- **Incremental (padrão, cron):** `python3 pipeline/buscar_editais.py` — busca as publicações dos
  últimos 5 dias nas modalidades mais usadas por software/serviços (Pregão elet., Dispensa,
  Inexigibilidade, Credenciamento, Concorrência), filtra pela taxonomia e mescla na base.
- **Bootstrap:** `python3 pipeline/buscar_editais.py --full` — varre TODAS as propostas abertas do
  Brasil e **substitui** a base. Rode local (o volume derruba a varredura completa nos IPs do Actions).

## Secrets necessários (Settings → Secrets and variables → Actions)
- `MAIL_SERVER` (ex.: smtp.gmail.com)
- `MAIL_PORT` (ex.: 465)
- `MAIL_USERNAME` (conta Gmail remetente)
- `MAIL_PASSWORD` (senha de app do Gmail, sem espaços)
