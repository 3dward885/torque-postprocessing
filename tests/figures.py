"""Generate representative saved-stage plots and verify PDF/PNG properties."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plots import export_figure, make_figure, FONT_SHA
from storage import load_config, atomic_json
from validate import read_treated


def main():
    from PIL import Image
    from pypdf import PdfReader
    result = load_config(ROOT/"validation/regression/new_rot1_midrange/provenance.json")
    reference, _ = read_treated(ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/inputs/Rot1treatedHo2thd4Pc.dat")
    folder = ROOT/"validation/plots"
    reports = []
    for view in ("stages", "background", "comparison", "residual"):
        existing = [folder / f"P003_{view}.{ext}" for ext in ("pdf", "png")]
        pdf, png = existing if all(p.exists() for p in existing) else export_figure(result, "P003", folder, view, reference)
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
        assert names and all("GillSans" in n.replace("-", "") for n in names), names
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
        clipped = []
        for label in labels:
            box = label.get_window_extent(renderer)
            if box.width and box.height and (box.x0 < 0 or box.y0 < 0 or box.x1 > bounds.x1 or box.y1 > bounds.y1):
                clipped.append(str(label))
        assert not clipped, clipped
        reports.append({"view": view, "PDF": str(Path(pdf).relative_to(ROOT)), "PNG": str(Path(png).relative_to(ROOT)),
                        "fonts": names, "all_fonts_embedded": True, "PNG_pixels": image.size,
                        "PNG_dpi": image.info.get("dpi"), "text_or_legend_clipping": clipped,
                        "font_sha256": FONT_SHA})
    atomic_json(folder/"figure_checks.json", reports)
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()

