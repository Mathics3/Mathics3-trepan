# -*- coding: utf-8 -*-
#  Copyright (C) 2024 Rocky Bernstein
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Our local modules
from trepan.processor.command.handle import HandleCommand as TrepanHandleCommand


class HandleCommand(TrepanHandleCommand):
    pass


if __name__ == "__main__":
    from trepan import debugger as Mdebugger

    d = Mdebugger.Trepan()
    command = HandleCommand(d.core.processor)
    command.run(["handle", "USR1"])
    command.run(["handle", "term", "stop"])
    pass
