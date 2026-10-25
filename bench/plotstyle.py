"""Shared figure style for every results/**/figs plot (static paper figures).

Categorical slots in fixed order (validated: CVD / normal-vision separation pass on adjacent pairs; aqua and
yellow are below 3:1 contrast on the light surface, so every series also gets a distinct marker and a legend
entry, and every plotted number is also tabulated in the paper). Text stays in neutral ink, never series color.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def apply() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.titlesize": 10, "axes.labelsize": 9, "xtick.labelsize": 8,
        "ytick.labelsize": 8, "legend.fontsize": 7, "legend.frameon": False, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "axes.spines.top": False,
        "axes.spines.right": False, "lines.linewidth": 1.6, "lines.markersize": 5,
        "axes.prop_cycle": matplotlib.cycler(color=SERIES), "font.family": "DejaVu Sans",
    })


def style(i: int) -> dict:
    """Series i: fixed color slot + marker (secondary encoding)."""
    return {"color": SERIES[i % len(SERIES)], "marker": MARKERS[i % len(MARKERS)]}


def save(fig, path) -> None:
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(path) + ".png" if not str(path).endswith(".png") else path, dpi=200)
    fig.savefig(str(path).removesuffix(".png") + ".pdf")
    plt.close(fig)
