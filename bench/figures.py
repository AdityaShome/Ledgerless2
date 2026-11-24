"""Figures for results/. Reads the CSVs only. Palette: validated categorical slots (fixed order).

Colour is never the only channel: heatmap cells carry their value, lines carry markers and a
legend. Two measures of different scale are drawn in separate panels, never on a dual axis.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

SURFACE, INK, INK2, GRID = "#fcfcfb", "#1a1a19", "#52514e", "#e3e2de"
# categorical slots in fixed order: blue, orange, aqua, magenta, violet, red
SERIES = {"default_sdk": "#eb6834", "request_id": "#e87ba4", "ours": "#2a78d6",
          "ours_fine": "#e34948", "ours_fine_persist": "#6250d6", "temporal_bridge": "#1baf7a"}
MARKERS = {"default_sdk": "s", "request_id": "D", "ours": "o", "ours_fine": "^",
           "ours_fine_persist": "v", "temporal_bridge": "P"}
SEQ = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#9ec5f4", "#3987e5", "#184f95"])
SC = ["F0_clean", "F1_crash_after_effect", "F2_receipt_lost", "F3_duplicate_delivery",
      "F4_replica_failover", "F5_replan_on_replay", "F6_partition_transient",
      "F6_partition_permanent", "F7_forged_receipt", "F8_upstream_abort"]
SC_LABEL = ["F0\nclean", "F1\ncrash", "F2\nlost\nreceipt", "F3\ndup\ndelivery", "F4\nfailover",
            "F5\nre-plan", "F6\npartition\n(transient)", "F6\npartition\n(permanent)",
            "F7\nforged\nreceipt", "F8\nupstream\nabort"]
SYS_ORDER = ["default_sdk", "request_id", "saga", "temporal_bridge", "ours_no_intents",
             "ours_no_resolve", "digest_only_coarse", "digest_only_medium", "digest_only_fine",
             "ours_coarse", "ours", "ours_fine", "ours_medium_persist", "ours_fine_persist"]


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def _fig(*a, **k):
    fig, ax = plt.subplots(*a, **k)
    fig.patch.set_facecolor(SURFACE)
    for x in (ax if hasattr(ax, "__iter__") else [ax]):
        _style(x)
    return fig, ax


def pooled(rows, key, **flt):
    sel = [r for r in rows if all(r[k] == v for k, v in flt.items())]
    n = sum(float(r["n"]) for r in sel)
    if key.endswith(("_mean", "_p50", "_p95")):
        return sum(float(r[key]) * float(r["n"]) for r in sel) / n
    return sum(float(r[key]) for r in sel) / n


def heatmap(grid, key, title, path, cbar_label, cmap=SEQ) -> None:
    systems = [s for s in SYS_ORDER if any(r["system"] == s for r in grid)]
    data = [[100 * pooled(grid, key, system=s, scenario=sc) for sc in SC] for s in systems]
    fig, ax = _fig(figsize=(11, 6.2))
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(SC)))
    ax.set_xticklabels(SC_LABEL, fontsize=7.5)
    ax.set_yticks(range(len(systems)))
    ax.set_yticklabels(systems, fontsize=8)
    ax.xaxis.tick_top()
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v:.0f}" if v == int(v) else f"{v:.1f}", ha="center", va="center",
                    fontsize=7.5, color="white" if v > 55 else INK)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, pad=44, loc="left", fontsize=11)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label(cbar_label, color=INK2, fontsize=8)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def sweep(rows, path) -> None:
    fig, ax = _fig(figsize=(7.5, 4.6))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s, color in SERIES.items():
        pts = sorted((float(r["p_replan"]), 100 * float(r["dup_runs"]) / float(r["n"]))
                     for r in rows if r["system"] == s)
        if not pts:
            continue
        ax.plot([p for p, _ in pts], [v for _, v in pts], color=color, lw=2,
                marker=MARKERS[s], ms=7, mec=SURFACE, mew=1.5, label=s,
                ls="--" if s in ("ours", "temporal_bridge") else "-")
    ax.set_xlabel("p_replan: chance a retry re-plans the request")
    ax.set_ylabel("% of runs with a duplicate effect")
    ax.set_title("C1: duplicates vs re-planning (F5, depth 3, 500 seeds)", loc="left", fontsize=11)
    ax.text(0.99, 0.10, "ours, ours_fine_persist and temporal_bridge\nall sit at 0% (overlapping)",
            transform=ax.transAxes, ha="right", fontsize=8, color=INK2)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="center left")
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def rq4(rows, path) -> None:
    fig, ax = _fig(figsize=(7, 4.4))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    x = range(len(rows))
    b1 = ax.bar([i - 0.2 for i in x], [100 * float(r["false_dedup_rate"]) for r in rows], 0.38,
                color="#2a78d6", label="false dedup: legitimate effect blocked")
    b2 = ax.bar([i + 0.2 for i in x], [100 * float(r["missed_dedup_rate"]) for r in rows], 0.38,
                color="#eb6834", label="missed dedup: re-planned duplicate ran")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5,
                    f"{b.get_height():.0f}", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(list(x))
    ax.set_xticklabels([r["policy"] for r in rows])
    ax.set_ylim(0, 112)
    ax.set_ylabel("%")
    ax.set_title("RQ4: digest granularity trade-off", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper center")
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def overhead(grid, path) -> None:
    systems = ["default_sdk", "request_id", "saga", "temporal_bridge", "ours",
               "ours_fine_persist"]
    base_m = pooled(grid, "msgs_mean", system="default_sdk", scenario="F0_clean")
    base_b = pooled(grid, "bytes_mean", system="default_sdk", scenario="F0_clean")
    panels = [
        ("Messages per chain, fault-free (x default SDK)", base_m, "msgs_mean"),
        ("Bytes per chain, fault-free (x default SDK)", base_b, "bytes_mean"),
    ]
    fig, axes = _fig(1, 2, figsize=(10.5, 4.2))
    for ax, (title, base, key) in zip(axes, panels, strict=True):
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        vals = [pooled(grid, key, system=s, scenario="F0_clean") / base for s in systems]
        ax.barh(range(len(systems)), vals, 0.55, color="#2a78d6")
        for i, v in enumerate(vals):
            ax.text(v + max(vals) * 0.015, i, f"{v:.2f}x", va="center", fontsize=8, color=INK2)
        ax.set_yticks(range(len(systems)))
        ax.set_yticklabels(systems, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, max(vals) * 1.18)
        ax.set_title(title, loc="left", fontsize=10)
    fig.suptitle("C4: overhead (toy payload is about 40 bytes, so byte ratios are inflated)",
                 x=0.01, ha="left", fontsize=10, color=INK2)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fault_cost(grid, path) -> None:
    systems = ["default_sdk", "request_id", "saga", "temporal_bridge", "ours"]
    scs = [("F0_clean", "F0 clean"), ("F1_crash_after_effect", "F1 crash"),
           ("F5_replan_on_replay", "F5 re-plan")]
    fig, axes = _fig(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, (sc, lab) in zip(axes, scs, strict=True):
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        vals = [pooled(grid, "msgs_mean", system=s, scenario=sc) for s in systems]
        ax.barh(range(len(systems)), vals, 0.55, color="#2a78d6")
        for i, v in enumerate(vals):
            ax.text(v + 0.5, i, f"{v:.1f}", va="center", fontsize=8, color=INK2)
        ax.set_yticks(range(len(systems)))
        ax.set_yticklabels(systems, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, 45)
        ax.set_title(f"{lab}: mean messages per chain", loc="left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def make_all(grid, sweep_rows, rq4_rows, figs: Path) -> None:
    figs.mkdir(parents=True, exist_ok=True)
    heatmap(grid, "dup_runs", "% of runs with a duplicate effect (500 seeds x 6 shapes per cell)",
            figs / "duplicates_by_scenario.png", "% runs with duplicate")
    heatmap(grid, "completed", "% of runs that completed (quarantined or aborted chains do not count)",
            figs / "completion_by_scenario.png", "% runs completed")
    sweep(sweep_rows, figs / "c1_replan_sweep.png")
    rq4(rq4_rows, figs / "rq4_granularity.png")
    overhead(grid, figs / "c4_overhead.png")
    fault_cost(grid, figs / "c4_cost_under_faults.png")
