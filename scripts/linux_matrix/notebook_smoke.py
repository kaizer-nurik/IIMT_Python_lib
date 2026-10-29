"""Execute installed-wheel notebooks against external localhost mocks only."""

import argparse
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for dual in (False, True):
        notebook = nbformat.read(ROOT / "notebooks/csv_single_dual.ipynb", as_version=4)
        source = notebook.cells[1].source
        assert "USE_MOCK = True" in source and "VIEWER = False" in source
        source = source.replace("DUAL = True", f"DUAL = {dual}")
        source = source.replace("RUN_APPROACH = False", "RUN_APPROACH = True")
        source = source.replace("RUN_CSV = False", "RUN_CSV = True")
        source = "\n".join(
            (
                f"OUTPUT = Path({str(args.output / ('dual' if dual else 'single'))!r})"
                if line.startswith("OUTPUT = ")
                else line
            )
            for line in source.splitlines()
        )
        source += (
            f"\nimport sys, iimt\nassert sys.prefix == {sys.prefix!r}, sys.prefix"
            "\nassert 'site-packages' in iimt.__file__, iimt.__file__\n"
        )
        notebook.cells[1].source = source
        NotebookClient(notebook, timeout=180, resources={"metadata": {"path": str(ROOT)}}).execute()
        outputs = [o for c in notebook.cells if c.cell_type == "code" for o in c.outputs]
        assert not [o for o in outputs if o.output_type == "error"]
        pngs = [o for o in outputs if "image/png" in o.get("data", {})]
        text = "\n".join(o.get("text", "") for o in outputs)
        assert text.count("'status': 'succeeded'") >= 2, text
        assert len(pngs) >= 2
        nbformat.write(notebook, args.output / f'notebook_{"dual" if dual else "single"}.ipynb')
        print(f"PASS installed-wheel notebook dual={dual}: >=2 succeeded motions, {len(pngs)} PNGs")


if __name__ == "__main__":
    main()
