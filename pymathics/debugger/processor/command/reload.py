# -*- coding: utf-8 -*-
# Copyright (C) 2024 Rocky Bernstein <rocky@gnu.org>
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import importlib
import inspect

# Our local modules
from pymathics.debugger.processor.command.base_cmd import DebuggerCommand


class ReloadCommand(DebuggerCommand):
    """**reload** *command-name*

    Reload debugger command *command-name*.

    This command is usually used by Mathics3 debugger developers working on the debugger

    Example:
    --------

        reload backtrace
    """

    short_help = "reload a Mathics3 Debugger command"

    DebuggerCommand.setup(locals(), category="support", min_args=1, max_args=1)

    def run(self, args):
        cmd_name = args[1]
        proc = self.proc
        if cmd_name in proc.commands:
            command_module = importlib.import_module(proc.commands[cmd_name].__module__)
            importlib.reload(command_module)
            classnames = [tup[0] for tup in inspect.getmembers(command_module, inspect.isclass) if ("DebuggerCommand" != tup[0] and tup[0].endswith("Command"))]
            if len(classnames) == 1:
                try:
                    instance = getattr(command_module, classnames[0])(proc)
                except Exception:
                    print(
                        f"Error loading {classnames[0]} from mod_name, sys.exc_info()[0]"
                    )
                    return

                # FIXME: should we also replace object in proc.cmd_instances?
                proc.commands[cmd_name] = instance
                self.msg(f'reloaded command "{cmd_name}"')
        else:
            self.errmsg(f'command "{cmd_name}" not found as a debugger command"')
    pass


# Demo it
if __name__ == "__main__":
    from pymathics.debugger.processor.command import mock as Mmock

    dbgr, cmd = Mmock.dbg_setup()
    command = ReloadCommand(cmd)
    for cmdline in ["reload up"]:
        args = cmdline.split()
        cmd_argstr = cmdline[len(args[0]) :].lstrip()
        cmd.cmd_argstr = cmd_argstr
        command.run(args)
        pass
    pass
