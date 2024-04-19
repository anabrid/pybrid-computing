# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

# TODO: Refactor out common code with Model-1 data exporters and make abstraction for command line

import dataclasses
import typing

from pybrid.redac.run import Run


# TODO: Implement a lookup for different data types
# _REGISTRY = {}
# def get_exporter(format):
#     return _REGISTRY[format]


class BaseExporter:
    FORMAT = None

    def export(self, run, **kwargs):
        ...


class DatExporter(BaseExporter):
    FORMAT = "dat"

    def __init__(self, file: typing.IO):
        self._file = file

    def _write_line(self, line=""):
        self._file.write(line)
        self._file.write("\n")

    def _write_header_line(self, key, value):
        self._write_line(f"# {key} = {value}")

    def _write_header(self, run):
        self._write_line("# Run result")
        for key in ("id_", "created"):
            self._write_header_line(key, getattr(run, key))
        for flag in dataclasses.fields(run.flags):
            flag_set = "Yes" if getattr(run.flags, flag.name) else "No"
            self._write_header_line("flag " + flag.name, flag_set)

    def _write_data_line(self, idx, data_pkg):
        self._write_line(str(idx) + "\t" + "\t".join(map(str, data_pkg)))

    def _write_data(self, run: Run):
        if not run.data:
            self._write_line("# No data.")
            return

        data_header = "# idx\t" + "\t".join(map(str, run.data.keys()))
        self._write_line(data_header)

        for idx, data_pkg in enumerate(zip(*run.data.values())):
            self._write_data_line(idx, data_pkg)

    def export(self, run):
        self._write_header(run)
        self._write_line("#")
        self._write_data(run)
