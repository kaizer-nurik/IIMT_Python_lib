"""Run installed-wheel notebook cells on localhost mocks; never contact hardware."""

import re
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    for dual in (False, True):
        notebook = nbformat.read(ROOT / "notebooks/csv_single_dual.ipynb", as_version=4)
        config = notebook.cells[1].source
        # Override only the in-memory test copy, regardless of user's saved flags.
        for key, value in {
            "DUAL": repr(dual),
            "USE_MOCK": "True",
            "VIEWER": "False",
            "RUN_APPROACH": "True",
            "RUN_CSV": "True",
            "TIME_SCALE": "2.0",
        }.items():
            config, count = re.subn(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", config)
            assert count == 1, key
        assert "USE_MOCK = True" in config and "VIEWER = False" in config
        # A global kernelspec must not silently test a different Python ABI.
        config += (
            "\nimport sys, iimt\n"
            f"assert Path(sys.executable).resolve() == Path({sys.executable!r}).resolve(), "
            "sys.executable\n"
            f"assert Path(sys.prefix).resolve() == Path({sys.prefix!r}).resolve(), sys.prefix\n"
            "assert Path(iimt.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "
            "iimt.__file__\n"
        )
        notebook.cells[1].source = config
        NotebookClient(notebook, timeout=180, resources={"metadata": {"path": str(ROOT)}}).execute()
        errors = [
            o
            for c in notebook.cells
            if c.cell_type == "code"
            for o in c.outputs
            if o.output_type == "error"
        ]
        pngs = [
            o
            for c in notebook.cells
            if c.cell_type == "code"
            for o in c.outputs
            if "image/png" in o.get("data", {})
        ]
        output = "\n".join(
            o.get("text", "") for c in notebook.cells if c.cell_type == "code" for o in c.outputs
        )
        assert not errors, errors
        assert (
            "'status': 'succeeded'" in output and output.count("'status': 'succeeded'") >= 2
        ), output
        assert len(pngs) >= 2, "No actual inline plot output"
        folder = ROOT / "results"
        folder.mkdir(exist_ok=True)
        nbformat.write(notebook, folder / f"notebook_{'dual' if dual else 'single'}_executed.ipynb")
        print(f"PASS actual notebook dual={dual}, {len(pngs)} inline PNGs")


if __name__ == "__main__":
    main()
