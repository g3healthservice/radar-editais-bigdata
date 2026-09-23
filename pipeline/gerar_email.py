#!/usr/bin/env python3
"""Gera o corpo HTML do e-mail com os editais NOVOS desde a última execução."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Link com token de acesso permanente (dono) — para não esbarrar no gate de convite.
DASHBOARD_URL = "https://g3healthservice.github.io/radar-editais-engenharia/#k=eyJwZXJtIjp0cnVlLCJuIjoiRzMifQ.c6brfm"

ESFERA_COR = {"Federal": "#0B3B5A", "Estadual": "#0E7C7B", "Municipal": "#2D6A4F", "Não informado": "#777"}


def fmt_moeda(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_data(iso):
    """Data + hora (HH:MM) no formato brasileiro."""
    if not iso:
        return "—"
    data, _, hora = iso.partition("T")
    y, m, d = data.split("-")
    return f"{d}/{m}/{y}" + (f" {hora[:5]}" if hora else "")


def fmt_data_hora(iso):
    """Data + hora EXATA (HH:MM:SS) no formato brasileiro — usado na emissão."""
    if not iso:
        return "—"
    data, _, hora = iso.partition("T")
    y, m, d = data.split("-")
    return f"{d}/{m}/{y}" + (f" {hora[:8]}" if hora else "")


def linha(item):
    cor = ESFERA_COR.get(item["esfera"], "#777")
    ata = "✅ Aceita ATA" if item["srp"] else "— Sem ATA"
    fontes = ", ".join(item["fonteRecurso"])
    eixos = " · ".join(item.get("eixos", []))
    prio = '<span style="color:#E9A400">⭐ </span>' if item.get("prioritario") else ""
    if item.get("categoria") == "monitorar":
        tag = '<span style="background:#fbe7cf;color:#B45309;border-radius:10px;padding:1px 8px;font-size:11px;margin-left:6px">Monitorar</span>'
    else:
        tag = '<span style="background:#e2f5ea;color:#2D6A4F;border-radius:10px;padding:1px 8px;font-size:11px;margin-left:6px">Disputar</span>'
    return f"""
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee">
        {prio}<b>{item['orgao'] or '—'}</b>
        <span style="background:{cor};color:#fff;border-radius:10px;padding:1px 8px;font-size:11px;margin-left:6px">{item['esfera']}</span>{tag}
        <br><span style="color:#555;font-size:12.5px">{item['municipio'] or '—'}/{item['uf'] or '—'} · {item['modalidade'] or ''}</span>
        <br><span style="font-size:12px;color:#125E8A">Eixo(s): {eixos or '—'}</span>
        <br><span style="font-size:12.5px">{(item['objeto'] or '')[:220]}</span>
        <br><span style="font-size:12px;color:#555">Valor estimado: <b>{fmt_moeda(item['valorEstimado'])}</b> · Prazo proposta: <b>{fmt_data(item['dataEncerramentoProposta'])}</b> · {ata}</span>
        <br><span style="font-size:11px;color:#888">Emitido em: {fmt_data_hora(item['dataPublicacaoPncp'])}</span>
        <br><span style="font-size:12px;color:#6a4c93">Fonte de recurso (indício no texto): {fontes}</span>
        <br><a href="{item['linkEdital'] or '#'}" style="font-size:12px">Abrir edital ↗</a>
      </td>
    </tr>"""


def main():
    dataset = json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))
    novos = json.loads((HERE / "novos.json").read_text(encoding="utf-8"))

    resumo_eixo = {}
    for i in dataset["itens"]:
        for e in i.get("eixos", []):
            resumo_eixo[e] = resumo_eixo.get(e, 0) + 1
    top_eixos = sorted(resumo_eixo.items(), key=lambda kv: -kv[1])

    n_prio = sum(1 for i in novos if i.get("prioritario"))
    n_monit = sum(1 for i in novos if i.get("categoria") == "monitorar")

    # Ordena os novos: prioritários primeiro, depois disputar, monitorar por último.
    ordem = sorted(
        novos,
        key=lambda i: (0 if i.get("prioritario") else (1 if i.get("categoria") == "disputar" else 2),
                       i.get("dataEncerramentoProposta") or "9999"),
    )

    linhas_html = "".join(linha(i) for i in ordem[:80])
    aviso_corte = "" if len(novos) <= 80 else f"<p style='color:#9B2226'>Mostrando os 80 primeiros de {len(novos)} novos editais — veja o restante no dashboard.</p>"

    html = f"""<html><head><meta charset="UTF-8"></head><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:760px">
    <h2 style="color:#0B3B5A">🩺 Radar de Editais — Big Data · Gestão em Saúde (PNCP)</h2>
    <p><b>{len(novos)} editais novos</b> desde a última verificação — sendo <b>{n_prio}</b> prioritários ⭐ e <b>{n_monit}</b> para monitorar. Total em aberto no Brasil: <b>{dataset['totalCaptado']}</b>.</p>
    <p style="font-size:13px;color:#555">Por eixo (total atual em aberto): {' · '.join(f"{k}: {v}" for k,v in top_eixos)}</p>
    <p><a href="{DASHBOARD_URL}" style="background:#0B3B5A;color:#fff;padding:8px 14px;border-radius:6px;text-decoration:none">Abrir dashboard completo (filtros por eixo, ordenação, todos os itens)</a></p>
    {aviso_corte}
    <table style="width:100%;border-collapse:collapse">{linhas_html}</table>
    <p style="font-size:11px;color:#888;margin-top:16px">Etiquetagem por eixo/CNAE e fonte de recurso são heurísticas (texto do objeto) — confirmar sempre no edital. Itens "Monitorar" são do mercado de operadoras/planos. Fonte: PNCP (dados abertos).</p>
    </body></html>"""

    (HERE.parent / "email_novos.html").write_text(html, encoding="utf-8")
    print(f"E-mail gerado com {len(novos)} itens novos.")


if __name__ == "__main__":
    main()
