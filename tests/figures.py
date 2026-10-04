"""Generate representative saved-stage plots and verify PDF/PNG properties."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plots import export_figure, make_figure, FONT_SHA, FONT, font_status
from cli import run_entry
from storage import load_session
from matplotlib import font_manager
from storage import load_config, atomic_json
from validate import read_treated


def main(session, output):
    from PIL import Image
    from pypdf import PdfReader
    raw, cfg = load_session(session)[0]
    result = run_entry(raw, cfg)
    folder = Path(output).resolve()
    reference = None
    reports = []
    for view in ("baseline_uncentered", "baseline_corrected", "background"):
        pdf, png = export_figure(result, "P003", folder, view, reference)
        reader = PdfReader(pdf)
        page = reader.pages[0]
        names, embedded = [], []
        for value in page["/Resources"]["/Font"].values():
            font = value.get_object()
            names.append(str(font.get("/BaseFont")))
            descendants = font.get("/DescendantFonts", [font])
            for descendant in descendants:
                desc = descendant.get_object().get("/FontDescriptor")
                if desc:
                    embedded.append(any(k in desc.get_object() for k in ("/FontFile", "/FontFile2", "/FontFile3")))
        assert names and all("ArialMT" in n for n in names), names
        assert embedded and all(embedded)
        image = Image.open(png)
        expected = (2400, 1830 if view == "background" else 1800)
        assert image.size == expected, (view, image.size)
        assert abs(float(page.mediabox.width) - 576) < .01
        assert abs(float(page.mediabox.height) - (439.2 if view == "background" else 432)) < .01
        fig = make_figure(result, "P003", view, reference)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        renderer = canvas.get_renderer()
        bounds = fig.bbox
        labels = []
        for ax in fig.axes:
            labels.extend([ax.xaxis.label, ax.yaxis.label, ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text()])
            labels.extend(t for t in ax.get_xticklabels() if ax.get_xlim()[0] <= t.get_position()[0] <= ax.get_xlim()[1])
            labels.extend(t for t in ax.get_yticklabels() if ax.get_ylim()[0] <= t.get_position()[1] <= ax.get_ylim()[1])
            if ax.get_legend():
                labels.append(ax.get_legend())
        for ax in fig.axes:
            assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
            assert ax.spines["left"].get_linewidth() == 1.2
            assert ax.xaxis.label.get_fontsize() == 22
            assert ax.yaxis.label.get_fontsize() == 22
            assert not ax.get_title()
            assert not any(line.get_visible() for line in ax.get_xgridlines()+ax.get_ygridlines())
            assert ax.xaxis.get_major_ticks()[0].tick1line.get_markersize() == 6
            assert ax.xaxis.get_minor_ticks()[0].tick1line.get_markersize() == 3
            assert all(t.label1.get_fontsize() == 18 for t in ax.xaxis.get_major_ticks())
            if ax.get_legend():
                assert all(t.get_fontsize() == 12 for t in ax.get_legend().get_texts())
            if view == "background":
                samples, curve = ax.lines
                assert samples.get_markersize() == 7.5 and samples.get_linestyle() == "None"
                assert samples.get_markerfacecolor() == "black"
                assert curve.get_color() == "#FF0000" and curve.get_linewidth() == .5
            for text in [ax.xaxis.label,ax.yaxis.label,*ax.get_xticklabels(),*ax.get_yticklabels()]:
                assert Path(font_manager.findfont(text.get_fontproperties())).resolve() == FONT.resolve()
        clipped = []
        for label in labels:
            box = label.get_window_extent(renderer)
            if box.width and box.height and (box.x0 < 0 or box.y0 < 0 or box.x1 > bounds.x1 or box.y1 > bounds.y1):
                clipped.append(str(label))
        assert not clipped, clipped
        reports.append({"view": view, "PDF": str(Path(pdf).relative_to(ROOT)), "PNG": str(Path(png).relative_to(ROOT)),
                        "fonts": names, "all_fonts_embedded": True, "PNG_pixels": image.size,
                        "PNG_dpi": image.info.get("dpi"), "text_or_legend_clipping": clipped,
                        "font_sha256": FONT_SHA, "font_resolution": font_status()})
    atomic_json(folder/"figure_checks.json", reports)
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default=str(ROOT/"validation/baseline_v1.1/gui_background/accepted_session.json"))
    parser.add_argument("--output", default=str(ROOT/"validation/baseline_v1.1/figures"))
    args = parser.parse_args()
    main(args.session, args.output)
