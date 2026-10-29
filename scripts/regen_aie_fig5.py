#!/usr/bin/env python3
"""Regenerate AIE Fig. 5 at 130 mm width from locked results (does not modify analysis/)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis" / "exploratory_aie"))

os.environ.setdefault("SOURCE_DATE_EPOCH", "0")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import run_aie_exploratory as aie  # noqa: E402


def make_figure_130mm(per_item, outcomes, out_pdf: Path, out_png: Path) -> dict:
    font_name = "Arial"
    plt.rcParams.update(
        {
            "font.family": font_name,
            "font.size": 8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.unicode_minus": False,
        }
    )
    blocks: list[dict] = []
    cat_pooled = {}
    for cat in aie.CAT_ORDER:
        cat_pooled[cat] = aie.category_pooled_r20(outcomes, "SELF_REFLECT", cat)
        sub = per_item[per_item.category == cat].copy()
        sub = sub.sort_values("SELF_REFLECT_est", ascending=True)
        for _, r in sub.iterrows():
            blocks.append(dict(r))

    y_positions = []
    y = 0.0
    gap = 0.6
    for i, row in enumerate(blocks):
        if i > 0 and row["category"] != blocks[i - 1]["category"]:
            y += gap
        y_positions.append(y)
        y += 1.0

    fig_w = 130.0 / 25.4  # 130 mm
    fig_h = min(6.5, 0.14 * y + 0.8)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    for y_i, row in zip(y_positions, blocks):
        cat = row["category"]
        color = aie.CAT_COLORS[cat]
        est = float(row["SELF_REFLECT_est"])
        lo = float(row["SELF_REFLECT_ci_lo"])
        hi = float(row["SELF_REFLECT_ci_hi"])
        ax.plot([lo, hi], [y_i, y_i], color=color, lw=1.0, solid_capstyle="round", zorder=2)
        ax.scatter(
            [est],
            [y_i],
            s=18,
            facecolors=color,
            edgecolors=color,
            marker="o",
            zorder=3,
            linewidths=0.6,
        )
        ne = float(row["NEUTRAL_EDIT_est"])
        ax.scatter(
            [ne],
            [y_i],
            s=16,
            facecolors="none",
            edgecolors=color,
            marker="o",
            zorder=3,
            linewidths=0.8,
        )

    for cat in aie.CAT_ORDER:
        ys = [y_positions[i] for i, r in enumerate(blocks) if r["category"] == cat]
        if not ys:
            continue
        ax.plot(
            [cat_pooled[cat], cat_pooled[cat]],
            [min(ys) - 0.35, max(ys) + 0.35],
            color=aie.CAT_COLORS[cat],
            lw=0.7,
            ls="--",
            alpha=0.7,
            zorder=1,
        )

    labels = [f"{r['item_id']}: {r['label']}" for r in blocks]
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("P(eroded by round 20)", fontsize=8)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(max(y_positions) + 0.8, min(y_positions) - 0.8)
    ax.axvline(0, color="#bbbbbb", lw=0.5, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    handles = [
        Line2D([0], [0], marker="o", color="k", markerfacecolor="k", markersize=5, lw=0, label="SELF_REFLECT"),
        Line2D(
            [0],
            [0],
            marker="o",
            color="k",
            markerfacecolor="none",
            markersize=5,
            lw=0,
            label="NEUTRAL_EDIT",
        ),
        Line2D([0], [0], color="k", ls="--", lw=0.8, label="Category pooled"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8, frameon=False)
    fig.tight_layout()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    # Fixed canvas size (= figsize) so PDF width is 130 mm; do not crop with bbox_inches=tight.
    meta = {"Title": aie.LABEL, "Creator": aie.LABEL, "Producer": aie.LABEL}
    fig.savefig(out_pdf, dpi=300, bbox_inches=None, metadata=meta)
    fig.savefig(out_png, dpi=300, bbox_inches=None)
    plt.close(fig)
    return {
        "font": font_name,
        "fig_w_mm": 130.0,
        "fig_w_in": fig_w,
        "base_fontsize": 8,
        "legend_fontsize": 8,
        "ytick_fontsize": 8,
        "xlabel_fontsize": 8,
    }


def main() -> None:
    h = aie.load_forced_hazard(ROOT)
    outcomes = aie.build_item_outcomes(h)
    meta = aie.load_item_meta(ROOT)
    crude = aie.crude_event_counts(h)
    per_item_df, _ = aie.per_item_estimates(outcomes, meta, crude)

    out_dir = ROOT / "results" / "exploratory_aie" / "figs"
    info = make_figure_130mm(
        per_item_df,
        outcomes,
        out_dir / "per_item_erosion.pdf",
        out_dir / "per_item_erosion.png",
    )
    # Copy into AIE build
    dest = ROOT / "paper_aie" / "figs" / "Fig5.pdf"
    dest.write_bytes((out_dir / "per_item_erosion.pdf").read_bytes())
    print(info)
    # Report measured width
    try:
        import pypdf

        box = pypdf.PdfReader(str(dest)).pages[0].mediabox
        w_pt = float(box.width)
        print(f"measured_width_pt={w_pt:.2f} measured_width_mm={w_pt * 25.4 / 72:.2f}")
    except Exception as e:
        print("width_measure_failed", e)


if __name__ == "__main__":
    main()
