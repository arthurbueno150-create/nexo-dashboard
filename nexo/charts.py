"""Geometria dos gráficos gerada em Python; SVG é apenas apresentação."""
import math
from .engine import format_number

COLORS = ["#1aab80", "#91d4bc", "#9e8ae8", "#f0bb7a", "#709bcd", "#d1d8e1", "#a9b5bb"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def short_number(value):
    value = float(value)
    if abs(value) >= 1_000_000:
        return format_number(value / 1_000_000) + " mi"
    if abs(value) >= 1000:
        return format_number(value / 1000) + " mil"
    return format_number(value)


def chart_geometry(result, mapping):
    temporal = mapping.date >= 0
    data = result["timeline"] if temporal else result["groups"][:12]
    keys = ["income", "expense"] if temporal and mapping.mode == "finance" else ["value"]
    numbers = [float(p[key]) for p in data for key in keys]
    low, high = min([0] + numbers), max([0] + numbers)
    if high == low:
        high = low + 1
    high += (high - low) * .08
    y = lambda value: round(230 - (float(value) - low) / (high - low) * 200, 2)
    x = lambda i: round(66 + (i / max(1, len(data) - 1)) * 600, 2)
    ticks = [dict(y=y(low + (high - low) * i / 4), label=short_number(low + (high - low) * i / 4)) for i in range(5)]
    labels, series = [], []
    for i, point in enumerate(data):
        name = point["name"]
        label = f"{MONTHS[int(name[5:7])-1]}/{name[2:4]}" if temporal else name
        labels.append(dict(x=x(i), label=label[:15], full=label, show=i % max(1, math.ceil(len(data) / 8)) == 0 or i == len(data) - 1))
    for j, key in enumerate(keys):
        points = [dict(x=x(i), y=y(p[key]), label=labels[i]["full"], value=format_number(p[key], mapping.currency)) for i, p in enumerate(data)]
        path = " ".join(("M" if i == 0 else "L") + f'{p["x"]},{p["y"]}' for i, p in enumerate(points))
        area = path + (f' L{points[-1]["x"]},{y(0)} L{points[0]["x"]},{y(0)} Z' if points else "")
        series.append(dict(points=points, path=path, area=area, color=["#19a97f", "#9a8ae7"][j], name=["Receitas", "Despesas"][j] if len(keys) == 2 else "Total"))
    bars = []
    if not temporal:
        width = min(34, 560 / max(1, len(data)))
        for i, point in enumerate(data):
            bars.append(dict(x=x(i) - width / 2, y=min(y(point["value"]), y(0)), width=width, height=max(1, abs(y(point["value"]) - y(0))), label=point["name"], value=format_number(point["value"], mapping.currency)))
    distribution = [dict(g) for g in result["groups"] if g["value"]]
    items = distribution[:6]
    if len(distribution) > 6:
        items.append(dict(name="Demais categorias", value=sum(g["value"] for g in distribution[6:]), count=0))
    offset = 0
    maximum = max([abs(float(g["value"])) for g in items] + [1])
    for i, group in enumerate(items):
        share = float(group["value"] / result["expense"]) if mapping.mode == "finance" and result["expense"] else 0
        group.update(color=COLORS[i], share=round(share * 100, 1), dash=max(0, share * 100 - .9), offset=-offset, width=abs(float(group["value"])) / maximum * 100)
        offset += share * 100
    return dict(temporal=temporal, labels=labels, series=series, bars=bars, ticks=ticks, baseline=y(0), items=items, empty=not data)

