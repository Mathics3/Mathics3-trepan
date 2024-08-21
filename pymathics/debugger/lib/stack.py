# -*- coding: utf-8 -*-

#   Copyright (C) 2024 Rocky Bernstein <rocky@gnu.org>
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
""" Functions for working with Python frames"""

import inspect
import linecache
import os
import os.path as osp
import re
from reprlib import repr
from typing import Optional

from trepan.lib.format import (
    Arrow,
    Filename,
    Function,
    LineNumber,
    Return,
    format_token,
)
from trepan.lib.pp import pp
from trepan.lib.printing import printf

_with_local_varname = re.compile(r"_\[[0-9+]]")


def count_frames(frame, count_start=0):
    """Return a count of the number of frames"""
    count = -count_start
    while frame:
        count += 1
        frame = frame.f_back
    return count


_re_pseudo_file = re.compile(r"^<.+>")


def format_stack_entry(
    dbg_obj, frame_lineno, lprefix=": ", include_location=True, color="plain"
):
    """Format and return a stack entry gdb-style.
    Note: lprefix is not used. It is kept for compatibility.
    """
    frame, lineno = frame_lineno
    filename = frame2file(dbg_obj.core, frame)

    s = ""
    if frame.f_code.co_name:
        funcname = frame.f_code.co_name
    else:
        funcname = "<lambda>"
        pass
    s = format_token(Function, funcname, highlight=color)

    args, varargs, varkw, local_vars = inspect.getargvalues(frame)
    if "<module>" == funcname and (
        [],
        None,
        None,
    ) == (
        args,
        varargs,
        varkw,
    ):
        is_module = True
        if is_exec_stmt(frame):
            fn_name = format_token(Function, "exec", highlight=color)
            source_text = deparse_source_from_code(frame.f_code)
            s += f" {format_token(Function, fn_name, highlight=color)}({source_text})"
        else:
            fn_name = get_call_function_name(frame)
            if fn_name:
                source_text = deparse_source_from_code(frame.f_code)
                if fn_name:
                    s += f" {format_token(Function, fn_name, highlight=color)}({source_text})"
            pass
    else:
        is_module = False
        try:
            params = inspect.formatargvalues(args, varargs, varkw, local_vars)
        except Exception:
            pass
        else:
            maxargstrsize = dbg_obj.settings["maxargstrsize"]
            if len(params) >= maxargstrsize:
                params = f"{params[0:maxargstrsize]}...)"
                pass
            s += params
        pass

    # Note: ddd can't handle wrapped stack entries (yet).
    # The 35 is hoaky though. FIXME.
    if len(s) >= 35:
        s += "\n    "

    if "__return__" in frame.f_locals:
        rv = frame.f_locals["__return__"]
        s += "->"
        s += format_token(Return, repr(rv), highlight=color)
        pass

    if include_location:
        is_pseudo_file = _re_pseudo_file.match(filename)
        add_quotes_around_file = not is_pseudo_file
        if is_module:
            if filename == "<string>":
                s += " in exec"
            elif not is_exec_stmt(frame) and not is_pseudo_file:
                s += " file"
        elif s == "?()":
            if is_exec_stmt(frame):
                s = "in exec"
                # exec_str = get_exec_string(frame.f_back)
                # if exec_str != None:
                #     filename = exec_str
                #     add_quotes_around_file = False
                #     pass
                # pass
            elif not is_pseudo_file:
                s = "in file"
                pass
            pass
        elif not is_pseudo_file:
            s += " called from file"
            pass

        if add_quotes_around_file:
            filename = f"'{filename}'"
        s += " %s at line %s" % (
            format_token(Filename, filename, highlight=color),
            format_token(LineNumber, "%r" % lineno, highlight=color),
        )
    return s


def print_stack_entry(proc_obj, i_stack, color="plain", opts={}):
    from trepan.api import debug; debug()
    frame_lineno = proc_obj.stack[len(proc_obj.stack) - i_stack - 1]
    frame, lineno = frame_lineno
    intf = proc_obj.intf[-1]
    if frame is proc_obj.curframe:
        intf.msg_nocr(format_token(Arrow, "->", highlight=color))
    else:
        intf.msg_nocr("##")
    intf.msg(
        "%d %s"
        % (i_stack, format_stack_entry(proc_obj.debugger, frame_lineno, color=color))
    )


def print_stack_trace(proc_obj, count=None, color="plain", opts={}):
    "Print ``count`` entries of the stack trace"
    if count is None:
        n = len(proc_obj.stack)
    else:
        n = min(len(proc_obj.stack), count)
    try:
        for i in range(n):
            print_stack_entry(proc_obj, i, color=color, opts=opts)
    except KeyboardInterrupt:
        pass
    return


def print_dict(s, obj, title):
    if hasattr(obj, "__dict__"):
        d = obj.__dict__
        if isinstance(d, dict):
            keys = list(d.keys())
            if len(keys) == 0:
                s += f"\n  No {title}"
            else:
                s += f"\n  {title}:\n"
            keys.sort()
            for key in keys:
                s += f"    '{key}':\t{d[key]}\n"
                pass
            pass
        pass
    return s


def eval_print_obj(arg, frame, format=None, short=False):
    """Return a string representation of an object"""
    try:
        if not frame:
            # ?? Should we have set up a dummy globals
            # to have persistence?
            val = eval(arg, None, None)
        else:
            val = eval(arg, frame.f_globals, frame.f_locals)
            pass
    except Exception:
        return 'No symbol "' + arg + '" in current context.'

    return print_obj(arg, val, format, short)


def print_obj(arg, val, format=None, short=False):
    """Return a string representation of an object"""
    what = arg
    if format:
        what = format + " " + arg
        val = printf(val, format)
        pass
    s = f"{what} = {val}"
    if not short:
        s += f"\n  type = {type(val)}"
        # Try to list the members of a class.
        # Not sure if this is correct or the
        # best way to do.
        s = print_dict(s, val, "object variables")
        if hasattr(val, "__class__"):
            s = print_dict(s, val.__class__, "class variables")
            pass
        pass
    return s


# Demo stuff above
if __name__ == "__main__":

    class MockDebuggerCore:
        def canonic_filename(self, frame):
            return frame.f_code.co_filename

        def filename(self, name):
            return name

        pass

    class MockDebugger:
        def __init__(self):
            self.core = MockDebuggerCore()
            self.settings = {"maxargstrsize": 80}
            pass

        pass

    frame = inspect.currentframe()
    print(frame2filesize(frame))
    pyc_file = osp.join(
        osp.dirname(__file__), "__pycache__", osp.basename(__file__)[:-3] + ".pyc"
    )
    print(pyc_file, getsourcefile(pyc_file))

    # m = MockDebugger()
    # print(format_stack_entry(m, (frame, 10,)))
    # print(format_stack_entry(m, (frame, 10,), color="dark"))
    # print("frame count: %d" % count_frames(frame))
    # print("frame count: %d" % count_frames(frame.f_back))
    # print("frame count: %d" % count_frames(frame, 1))
    # print("def statement: x=5?: %s" % repr(is_def_stmt("x=5", frame)))
    # # Not a "def" statement because frame is wrong spot
    # print(is_def_stmt("def foo():", frame))

    # def sqr(x):
    #     x * x

    # def fn(x):
    #     frame = inspect.currentframe()
    #     print(get_call_function_name(frame))
    #     return

    # print("=" * 30)
    # eval("fn(5)")
    # print("=" * 30)
    # print(print_obj("fn", fn))
    # print("=" * 30)
    # print(print_obj("len", len))
    # print("=" * 30)
    # print(print_obj("MockDebugger", MockDebugger))
    pass