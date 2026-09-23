#!/usr/bin/env python3
"""
Radar de editais para a Big Data (gestão em saúde) no PNCP.

Varre a API pública de consulta do PNCP (contratações com recebimento de
proposta em aberto, Brasil inteiro) e capta editais aderentes às frentes de
atuação da empresa, organizadas por bloco de CNAE:

  86.60-7/00  Apoio à gestão de saúde (eixo principal)
  62.02/62.03/63.11  Licenciamento de software / SaaS
  78.30-2/00  Gestão de RH para terceiros (escalas, ponto, dimensionamento)
  86.50-0/03  Psicologia / riscos psicossociais (NR-1)
  70.20-4/00 + 82.11-3/00  Consultoria e apoio administrativo
  66.21-5/02  Auditoria e consultoria atuarial
  86.30-5/03 + 86.50  Assistencial / telessaúde
  (monitorar)  Mercado de operadoras/planos — acompanhar, não disputar

Cada edital captado é etiquetado com TODOS os eixos/CNAEs que casou, com a
categoria (disputar/monitorar) e com um destaque (as "três de segunda-feira").

Uso: python3 buscar_editais.py            (incremental, roda no cron)
     python3 buscar_editais.py --full     (bootstrap: varre tudo, substitui a base)
Gera: dataset.json (dados completos), novos.json (itens novos desde a última
execução, para o e-mail) e atualiza estado.json (para o diff).
"""
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

API_PROPOSTA = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
API_PUBLICACAO = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
PAGE_SIZE = 50
HERE = Path(__file__).resolve().parent
ESTADO_PATH = HERE / "estado.json"
DATASET_PATH = HERE / "dataset.json"
NOVOS_PATH = HERE / "novos.json"

# Modo incremental: janela de dias (para trás) de publicações a re-buscar a cada execução.
# Cobre o atraso de publicação do PNCP e execuções que porventura falharam.
LOOKBACK_DIAS = 5
# Modalidades iteradas no incremental (o endpoint /publicacao exige informar a modalidade).
# Diferente do radar de obras: para software/serviços/consultoria em saúde as modalidades
# que mais importam são Pregão Eletrônico (6), Dispensa (8) e Inexigibilidade (9) —
# licenciamento de software e consultoria atuarial vivem muito em dispensa/inexigibilidade.
# Incluímos também Credenciamento (12, telessaúde) e Concorrência (4/5). Pré-qualificação
# (11) e Pregão presencial (7) são raros nessas frentes e ficam de fora do incremental
# (o bootstrap --full captura tudo, inclusive esses).
# ATENÇÃO: 8 e 9 têm volume alto por janela — o incremental fica mais pesado (~40 min);
# a cadência do cron foi afrouxada para 2h por causa disso.
MODALIDADES = [6, 8, 9, 12, 4, 5]

ESFERA_NOMES = {"F": "Federal", "E": "Estadual", "M": "Municipal", "N": "Não informado"}
PODER_NOMES = {"E": "Executivo", "L": "Legislativo", "J": "Judiciário", "N": "Não informado"}


def normalizar(txt):
    if not txt:
        return ""
    nfkd = unicodedata.normalize("NFKD", txt)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.lower()


# ---------------------------------------------------------------------------
# Taxonomia de captação — Big Data (gestão em saúde).
#
# Um edital é captado se o objeto casar QUALQUER padrão de QUALQUER bloco;
# registramos todos os eixos/CNAEs que casaram para o painel filtrar por frente.
# Padrões são aplicados sobre o texto NORMALIZADO (minúsculas, sem acento).
# Cada padrão é ou uma string regex (casa direto) ou uma tupla (a, b) que só
# casa se AMBOS os regex a e b aparecerem no texto (exige contexto).
# ---------------------------------------------------------------------------
TAXONOMIA = [
    {
        "cnae": "86.60-7/00",
        "eixo": "Apoio à gestão de saúde",
        "categoria": "disputar",
        "padroes": [
            r"(sistema|plataforma|software|solucao|ferramenta)\w*( integrad\w*)? de gestao\w* "
            r"(hospitalar|em saude|da saude|de saude|clinic|de unidade|de saude publica)",
            r"gestao (hospitalar|em saude|da saude|clinica) informatizad",
            r"prontuario eletronico",
            r"gestao de leito",
            r"regulacao (ambulatorial|assistencial|em saude|de (consulta|exame|leito|acesso|vaga))",
            r"central de regulacao",
        ],
    },
    {
        "cnae": "62.02/62.03/63.11",
        "eixo": "Licenciamento de software / SaaS",
        "categoria": "disputar",
        "padroes": [
            r"licenc\w* de uso de (sistema|software|programa|solucao|aplicativo)",
            r"licenciamento de (sistema|software|solucao)",
            r"sistema informatizado",
            r"software como servico",
            r"\bsaas\b",
            r"solucao em nuvem|hospedagem em nuvem|plataforma web",
        ],
    },
    {
        "cnae": "78.30-2/00",
        "eixo": "Gestão de RH / escalas e ponto",
        "categoria": "disputar",
        "padroes": [
            r"gestao de escala",
            r"escala\w* de (plantao|trabalho|servico|profissionais)",
            r"ponto eletronico|ponto biometric|controle de (ponto|frequencia|jornada)",
            r"dimensionamento de (pessoal|forca de trabalho|profissionais)",
            r"folha e frequencia|gestao de frequencia|folha de pagamento e frequencia",
        ],
    },
    {
        "cnae": "86.50-0/03",
        "eixo": "Psicologia / riscos psicossociais",
        "categoria": "disputar",
        "padroes": [
            r"risco\w* psicossocia",
            r"(gerenciamento|gestao|programa) de risco\w* ocupacion",
            r"programa de gerenciamento de risco|\bpgr\b",
            r"saude ocupacional|\bpcmso\b|saude e seguranca (do|no) trabalho|\bsst\b",
            r"qualidade de vida no trabalho|\bqvt\b|bem[- ]?estar (no|do|dos) (trabalho|servidor)",
        ],
    },
    {
        "cnae": "70.20-4/00 · 82.11-3/00",
        "eixo": "Consultoria / apoio administrativo",
        "categoria": "disputar",
        "padroes": [
            r"canal de denuncia|ouvidoria",
            r"programa de integridade|\bcompliance\b|governanca e integridade",
            (r"gestao de contrato", r"sistema|software|plataforma|informatizad|modulo|aplicativo"),
        ],
    },
    {
        "cnae": "66.21-5/02",
        "eixo": "Auditoria / consultoria atuarial",
        "categoria": "disputar",
        "padroes": [
            r"avaliacao atuarial|reavaliacao atuarial",
            r"calculo atuarial|nota tecnica atuarial",
            r"consultoria atuarial|assessoria atuarial|servico\w* atuari|estudo\w* atuari",
            (r"atuari", r"\brpps\b|previdenc"),
        ],
    },
    {
        "cnae": "86.30-5/03 · 86.50",
        "eixo": "Assistencial / telessaúde",
        "categoria": "disputar",
        "padroes": [
            r"telessaude|tele[- ]?saude",
            r"telemedicina",
            r"teleconsulta|tele[- ]?atendimento|telediagnostic|tele[- ]?interconsulta",
        ],
    },
    {
        "cnae": "—",
        "eixo": "Monitorar (operadoras/planos — não disputar)",
        "categoria": "monitorar",
        "padroes": [
            r"gest(ao|ora) de plano\w* de saude|administracao de plano\w* de saude|"
            r"operadora de plano de saude",
            r"autogestao (em|de|da)? ?saude",
            r"auditoria de contas medic|auditoria medica|analise de contas medic",
        ],
    },
]

# As "três de segunda-feira" — marcam prioritario=True (destaque no painel/e-mail).
PRIORITARIOS = [
    re.compile(r"(sistema|plataforma|software).{0,25}gestao\w* (hospitalar|em saude|da saude|de saude)"),
    re.compile(r"gestao de escala|ponto eletronico"),
    re.compile(r"risco\w* psicossocia"),
]


def _compilar_padrao(p):
    if isinstance(p, tuple):
        return (re.compile(p[0]), re.compile(p[1]))
    return re.compile(p)


TAXONOMIA_COMPILADA = [
    {**b, "padroes": [_compilar_padrao(p) for p in b["padroes"]]} for b in TAXONOMIA
]


def _bloco_casa(bloco, txt):
    for p in bloco["padroes"]:
        if isinstance(p, tuple):
            if p[0].search(txt) and p[1].search(txt):
                return True
        elif p.search(txt):
            return True
    return False


def casar_taxonomia(objeto):
    """Retorna dict com eixos/cnaes/categoria/prioritario, ou None se não captar."""
    txt = normalizar(objeto)
    eixos, cnaes, categorias = [], [], set()
    for bloco in TAXONOMIA_COMPILADA:
        if _bloco_casa(bloco, txt):
            eixos.append(bloco["eixo"])
            cnaes.append(bloco["cnae"])
            categorias.add(bloco["categoria"])
    if not eixos:
        return None
    # Se casou qualquer frente disputável, a oportunidade é "disputar"; só é
    # "monitorar" quando o ÚNICO casamento foi no bloco de operadoras/planos.
    categoria = "disputar" if "disputar" in categorias else "monitorar"
    prioritario = any(p.search(txt) for p in PRIORITARIOS)
    return {
        "eixos": eixos,
        "cnaes": cnaes,
        "categoria": categoria,
        "prioritario": prioritario,
    }


FONTE_KEYWORDS = [
    (re.compile(r"\bMAC\b"), "MAC (Média e Alta Complexidade)"),
    (re.compile(r"\bPAP\b"), "PAP"),
    (re.compile(r"\bFNS\b|Fundo Nacional de Sa[uú]de", re.I), "Fundo Nacional de Saúde"),
    (re.compile(r"Fundo Municipal de Sa[uú]de|\bFMS\b", re.I), "Fundo Municipal de Saúde"),
    (re.compile(r"Fundo Estadual de Sa[uú]de|\bFES\b", re.I), "Fundo Estadual de Saúde"),
    (re.compile(r"emenda parlamentar", re.I), "Emenda parlamentar"),
    (re.compile(r"conv[eê]nio", re.I), "Convênio"),
    (re.compile(r"recursos? pr[oó]prios?", re.I), "Recursos próprios"),
    (re.compile(r"recursos? do tesouro", re.I), "Recursos do Tesouro"),
    (re.compile(r"bloco de custeio", re.I), "Bloco de custeio SUS"),
]


def identificar_fonte(objeto, info_complementar):
    texto = f"{objeto or ''} {info_complementar or ''}"
    achados = []
    for regex, nome in FONTE_KEYWORDS:
        if regex.search(texto) and nome not in achados:
            achados.append(nome)
    return achados or ["Não identificado no texto (conferir edital)"]


# Alguns WAFs/servidores tratam o User-Agent padrão do Python (Python-urllib) vindo de
# IP de datacenter com hostilidade (timeout no connect). Um UA de navegador evita isso.
HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}
MAX_TENTATIVAS = 4
REQ_TIMEOUT = 25  # falha rápido em página morta; retries cobrem instabilidade
PAUSA_ENTRE_PAGINAS = 0.6  # espaçar reduz 429 (com 8/9 no incremental o volume é maior)
# Se mais que esta fração das páginas falhar, abortamos sem publicar (não sobrescreve
# a última base boa com um resultado parcial enganoso).
LIMITE_FALHAS = 0.08


# Estrutura vazia (usada para HTTP 204 / corpo vazio = "sem resultados", não é falha).
VAZIO = {"data": [], "totalPaginas": 0, "totalRegistros": 0}


def _buscar_url(url):
    """Retorna o JSON da URL (ou VAZIO para 204/sem conteúdo), ou None se falhar."""
    req = urllib.request.Request(url, headers=HEADERS)
    for tentativa in range(MAX_TENTATIVAS):
        ultima = tentativa == MAX_TENTATIVAS - 1
        try:
            with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as resp:
                if resp.status == 204:
                    return VAZIO
                corpo = resp.read().decode("utf-8").strip()
                return json.loads(corpo) if corpo else VAZIO
        except urllib.error.HTTPError as e:
            if e.code == 429 and not ultima:
                espera = int(e.headers.get("Retry-After", 5 * (tentativa + 1)))
                time.sleep(espera)
                continue
            if e.code >= 500 and not ultima:
                time.sleep(3 * (tentativa + 1))
                continue
            return None
        except (urllib.error.URLError, OSError, TimeoutError, socket.timeout):
            # cobre timeouts de connect/read e quedas de conexão (no Python 3.9
            # socket.timeout não é subclasse de TimeoutError).
            if ultima:
                return None
            time.sleep(3 * (tentativa + 1))
    return None


def _coletar_paginado(primeira_url, url_para_pagina, rotulo):
    """Coleta todas as páginas de uma consulta paginada, tolerando falhas de página."""
    primeira = _buscar_url(primeira_url)
    if primeira is None:
        raise RuntimeError(f"Não foi possível obter a primeira página do PNCP ({rotulo}).")
    total_paginas = primeira.get("totalPaginas", 1) or 1
    total_registros = primeira.get("totalRegistros", 0) or 0

    limite = int(os.environ.get("MAX_PAGINAS", "0")) or total_paginas
    limite = min(limite, total_paginas)

    todos = list(primeira.get("data", []) or [])
    falhas = 0
    for pagina in range(2, limite + 1):
        d = _buscar_url(url_para_pagina(pagina))
        if d is None:
            falhas += 1
            print(f"  [aviso] {rotulo} página {pagina} falhou — pulando", flush=True)
        else:
            todos.extend(d.get("data", []) or [])
        time.sleep(PAUSA_ENTRE_PAGINAS)

    if limite > 1 and falhas / (limite - 1) > LIMITE_FALHAS:
        raise RuntimeError(
            f"Muitas páginas falharam em {rotulo} ({falhas}/{limite - 1}) — abortando."
        )
    return todos, total_registros


def coletar_full():
    """Bootstrap: varre TODAS as contratações com proposta em aberto (Brasil, ~660 páginas)."""
    data_final = (date.today() + timedelta(days=365 * 3)).strftime("%Y%m%d")

    def url(p):
        return f"{API_PROPOSTA}?dataFinal={data_final}&pagina={p}&tamanhoPagina={PAGE_SIZE}"

    print("Modo FULL: varredura completa de propostas abertas (Brasil).", flush=True)
    brutos, total = _coletar_paginado(url(1), url, "proposta")
    print(f"Coletados {len(brutos)} registros (total aberto Brasil: {total}).", flush=True)
    return brutos, total


def coletar_incremental():
    """Incremental: busca publicações dos últimos LOOKBACK_DIAS dias, por modalidade."""
    di = (date.today() - timedelta(days=LOOKBACK_DIAS)).strftime("%Y%m%d")
    df = date.today().strftime("%Y%m%d")
    print(f"Modo INCREMENTAL: publicações de {di} a {df}, por modalidade.", flush=True)

    brutos = []
    for mod in MODALIDADES:
        base = f"{API_PUBLICACAO}?dataInicial={di}&dataFinal={df}&codigoModalidadeContratacao={mod}"

        def url(p, base=base):
            return f"{base}&pagina={p}&tamanhoPagina={PAGE_SIZE}"

        primeira = _buscar_url(url(1))
        if primeira is None or not primeira.get("data"):
            continue
        parciais, _ = _coletar_paginado(url(1), url, f"publicacao mod {mod}")
        brutos.extend(parciais)
        print(f"  modalidade {mod}: {len(parciais)} registros", flush=True)
        time.sleep(PAUSA_ENTRE_PAGINAS)

    # Dedup por numeroControlePNCP (uma contratação pode vir repetida entre páginas).
    vistos, unicos = set(), []
    for it in brutos:
        nc = it.get("numeroControlePNCP")
        if nc and nc not in vistos:
            vistos.add(nc)
            unicos.append(it)
    print(f"Incremental: {len(unicos)} contratações únicas na janela.", flush=True)
    return unicos


# Alguns órgãos preenchem o valor estimado com um sentinela (ex.: 9.999.999.999.999,99)
# ou valores absurdos. Acima de R$ 1 trilhão para uma única contratação é lixo — trata como
# "não informado" para não distorcer o total do dashboard.
LIMITE_VALOR_ABSURDO = 1e12


def sanitizar_valor(v):
    if v is None or v <= 0 or v >= LIMITE_VALOR_ABSURDO:
        return None
    return v


def classificar(item, match):
    org = item.get("orgaoEntidade", {})
    uni = item.get("unidadeOrgao", {})
    objeto = item.get("objetoCompra", "")
    info = item.get("informacaoComplementar", "")
    return {
        "numeroControlePNCP": item.get("numeroControlePNCP"),
        "orgao": org.get("razaoSocial"),
        "cnpj": org.get("cnpj"),
        "esfera": ESFERA_NOMES.get(org.get("esferaId"), "Não informado"),
        "poder": PODER_NOMES.get(org.get("poderId"), "Não informado"),
        "unidade": uni.get("nomeUnidade"),
        "municipio": uni.get("municipioNome"),
        "uf": uni.get("ufSigla"),
        "codigoIbge": uni.get("codigoIbge"),
        "objeto": objeto,
        "modalidade": item.get("modalidadeNome"),
        "srp": bool(item.get("srp")),
        "valorEstimado": sanitizar_valor(item.get("valorTotalEstimado")),
        "dataEncerramentoProposta": item.get("dataEncerramentoProposta"),
        "dataPublicacaoPncp": item.get("dataPublicacaoPncp"),
        "fonteRecurso": identificar_fonte(objeto, info),
        "eixos": match["eixos"],
        "cnaes": match["cnaes"],
        "categoria": match["categoria"],
        "prioritario": match["prioritario"],
        "linkEdital": item.get("linkSistemaOrigem"),
        "processo": item.get("processo"),
    }


def ainda_aberta(item, agora_iso):
    """True se a proposta ainda está em aberto (encerramento no futuro ou desconhecido)."""
    dt = item.get("dataEncerramentoProposta")
    return (dt is None) or (dt >= agora_iso)


def main():
    modo_full = "--full" in sys.argv

    # Base acumulada existente (dataset.json versionado no repo).
    base = {}
    if DATASET_PATH.exists():
        try:
            for i in json.loads(DATASET_PATH.read_text()).get("itens", []):
                base[i["numeroControlePNCP"]] = i
        except Exception:
            base = {}

    ids_antes = set(base.keys())

    if modo_full:
        brutos, _ = coletar_full()
        # No full, a base é substituída pelo conjunto recém-varrido.
        base = {}
    else:
        brutos = coletar_incremental()

    # Filtra pela taxonomia da Big Data e mescla na base (adiciona/atualiza por id).
    novos_captados = 0
    for it in brutos:
        match = casar_taxonomia(it.get("objetoCompra", ""))
        if match:
            reg = classificar(it, match)
            base[reg["numeroControlePNCP"]] = reg
            novos_captados += 1

    # Poda: remove contratações cuja proposta já encerrou (não estão mais abertas).
    agora_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    itens = [i for i in base.values() if ainda_aberta(i, agora_iso)]
    itens.sort(key=lambda x: (x["dataEncerramentoProposta"] or "9999"))

    # Novos para o e-mail: captados que apareceram AGORA (não estavam na base) e abertos.
    novos = [i for i in itens if i["numeroControlePNCP"] not in ids_antes]

    dataset = {
        "build": int(time.time()),
        "geradoEm": date.today().isoformat(),
        "modo": "full" if modo_full else "incremental",
        "totalCaptado": len(itens),
        "itens": itens,
    }
    DATASET_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=0), encoding="utf-8")
    NOVOS_PATH.write_text(json.dumps(novos, ensure_ascii=False, indent=0), encoding="utf-8")
    ESTADO_PATH.write_text(json.dumps({"ids": sorted(base.keys())}, ensure_ascii=False), encoding="utf-8")

    print(f"Editais captados em aberto na base: {len(itens)}")
    print(f"Novos nesta execução: {len(novos)}")
    print(f"TEM_NOVOS={1 if novos else 0}")


if __name__ == "__main__":
    sys.exit(main())
