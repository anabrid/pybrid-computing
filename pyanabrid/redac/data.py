# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

# TODO: Refactor out common code with Model-1 data exporters and make abstraction for command line

import dataclasses
import typing

from pyanabrid.redac.run import Run


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
