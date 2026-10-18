#!/usr/bin/env python
"""Free step: two charts from methods.json (run methods_chart.py first).
  methods_f1_cost.png   F1 against cost per event
  methods_pr.png        recall against precision
matplotlib is not a project dependency; run in a throwaway environment:
  uv run --no-project --with matplotlib python plot_methods.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data" / "interim" / "jev_selection"

COLOR = {"cohere": "#eb6834", "jev": "#2a78d6"}
SURFACE, INK, MUTED = "#fcfcfb", "#0b0b0b", "#52514e"

m = json.loads((DATA / "methods.json").read_text())["methods"]
for k, x in enumerate(m, 1):
    x["n"] = k
    x["sampled"] = "100 постов" in x["method"]


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    ax.set_xlabel(xlabel, color=MUTED); ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(color="#e4e3df", lw=0.8); ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTED)


def draw(ax, xk, yk, offsets):
    for x in m:
        ax.scatter(x[xk], x[yk], s=70, color=COLOR[x["kind"]], marker="o" if x["sampled"] else "s",
                   edgecolor=SURFACE, linewidth=2, zorder=3)
        dx, dy = offsets.get(x["n"], (6, 4))
        ax.annotate(str(x["n"]), (x[xk], x[yk]), xytext=(dx, dy), textcoords="offset points",
                    fontsize=9, color=INK)


def legend(fig):
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="s", ls="", color=COLOR["cohere"], ms=8, label="Cohere rerank-v3.5"),
         Line2D([], [], marker="s", ls="", color=COLOR["jev"], ms=8, label="Jev 1.13 + описание события"),
         Line2D([], [], marker="s", ls="", color=MUTED, ms=8, label="один порог на все события"),
         Line2D([], [], marker="o", ls="", color=MUTED, ms=8, label="порог на событие по 100 прочитанным постам")]
    fig.legend(handles=h, loc="upper center", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.5, 0.995))
    key = "\n".join(f"{x['n']:>2}. {x['method']}" for x in m)
    fig.text(0.07, 0.01, key, fontsize=8.5, color=INK, va="bottom", family="DejaVu Sans")


NOTE = ("Три новых события (атака дронов на Москву, встреча Путина и Лукашенко, высказывания Трампа), по 3 000 кандидатов.\n"
        "Эталон — метки Codex; метрики по событию, затем среднее трёх событий. Цена — на одно событие: Jev и Cohere замерены,\n"
        "описание события и чтение постов Codex — оценка по цене gpt-6.1-sol; DeepSeek и Qwen — замер.")

for name, xk, yk, title, xl, yl, off, lim in [
    ("methods_f1_cost.png", "usd", "f1", "F1 против цены", "Цена на событие, $", "F1",
     {8: (6, -11), 9: (6, 5), 7: (6, -11), 10: (6, -11), 6: (6, 5), 3: (6, 5), 4: (6, -11)}, None),
    ("methods_pr.png", "precision", "recall", "Полнота против точности", "Точность (precision)",
     "Полнота (recall)", {8: (6, 6), 9: (-12, -12), 7: (6, -12), 3: (6, 4), 4: (6, -12)}, (0.55, 1.0)),
]:
    fig = plt.figure(figsize=(9, 9.2), facecolor=SURFACE)
    ax = fig.add_axes([0.09, 0.36, 0.86, 0.53])
    style(ax, title, xl, yl)
    draw(ax, xk, yk, off)
    if lim:
        ax.set_xlim(*lim); ax.set_ylim(*lim)
    legend(fig)
    fig.text(0.07, 0.27, NOTE, fontsize=8, color=MUTED, va="top")
    fig.savefig(HERE / name, dpi=150, facecolor=SURFACE)
    print(HERE / name)
