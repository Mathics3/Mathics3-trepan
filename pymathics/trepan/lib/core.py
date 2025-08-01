# -*- coding: utf-8 -*-
#
#   Copyright (C) 2024-2025
#   Rocky Bernstein <rocky@gnu.org>
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
"""Debugger core routines.

This module contains the Debugger core routines for starting and
stopping trace event handling and breakpoint checking. See also
debugger for top-level Debugger class and module routine which
ultimately will call this. An event processor is responsible of
handling what to do when an event is triggered."""


# Common Python packages
import os
import os.path as osp
import sys
import threading
import types
from typing import Any, Dict, Set

import mathics.eval.tracing
import pyficache
import tracer
import trepan.clifns as Mclifns
from mathics.eval.tracing import skip_trivial_evaluation
from tracer.tracefilter import TraceFilter
from trepan.lib.breakpoint import BreakpointManager
from trepan.lib.default import START_OPTS, STOP_OPTS
from trepan.lib.stack import count_frames
from trepan.misc import option_set

from pymathics.trepan.tracing import event_filters
from pymathics.trepan.processor.cmdproc import CommandProcessor

IGNORE_CODE: Set[types.CodeType] = set([])

class DebuggerCore:
    DEFAULT_INIT_OPTS = {
        "processor": None,
        # How many step events to skip before
        # entering event processor? Zero (0) means stop at the next one.
        # A negative number indicates no eventual stopping.
        "step_ignore": 0,
        "ignore_filter": TraceFilter([tracer, mathics.eval.tracing]),
    }

    def __init__(self, debugger, opts: Dict[str, Any]={}):
        """Create a debugger object. But depending on the value of
        key 'start' inside hash `opts', we may or may not initially
        start tracing events (i.e. enter the debugger).

        See also `start' and `stop'.
        """

        def get_option(key: str) -> Any:
            return option_set(opts, key, self.DEFAULT_INIT_OPTS)

        self.bpmgr = BreakpointManager()
        self.current_bp = None
        self.debugger = debugger

        # When not None, it is a Python debugger object, which is right now trepan3k
        # debugger object. This is used so we can switch from the Mathics3 debugger into a
        # lower-level trepan3k debugger.
        self.python_debugger = None

        # Threading lock ensures that we don't have other traced threads
        # running when we enter the debugger. Later we may want to have
        # a switch to control.
        self.debugger_lock = threading.Lock()

        self.filename_cache = {}

        # Initially the event parameter of the event hook.
        # We can however modify it, such as for breakpoints
        self.event = None

        # The "arg" value in the callback
        self.event_arg = None

        # Is debugged program currently under execution?
        self.execution_status = "Pre-execution"

        # main_dirname is the directory where the script resides.
        # Filenames in co_filename are often relative to this.
        self.main_dirname = os.curdir

        proc_opts = get_option("proc_opts")
        self.processor = CommandProcessor(self, opts=proc_opts)
        # What events are considered in stepping. Note: 'None' means *all*.
        self.step_events = None
        # How many line events to skip before entering event processor?
        # If stop_level is None all breaks are counted otherwise just
        # those which less than or equal to stop_level.
        self.step_ignore = get_option("step_ignore")

        # We can register specific code to not stop in.
        # Typically this is debugger code like DebugEvaluation.eval()
        self.ignore_code = opts.get("ignore_code", IGNORE_CODE)

        # If stop_level is not None, then we are next'ing or
        # finish'ing and will ignore frames greater than stop_level.
        # We also will cache the last frame and thread number encountered
        # so we don't have to compute the current level all the time.
        self.last_frame = None
        self.last_level = 10000
        self.last_thread = None
        self.stop_level = None
        self.stop_on_finish = False

        self.last_lineno = None
        self.last_filename = None
        self.different_line = None

        # The reason we have stopped, e.g. 'breakpoint hit', 'next',
        # 'finish', 'step', or 'exception'.
        self.stop_reason = ""

        # self.trace_processor = Mtrace.PrintProcessor(self)

        # What routines (keyed by f_code) will we not trace into?
        self.ignore_filter = get_option("ignore_filter")

        self.search_path = sys.path  # Source filename search path

        # When trace_hook_suspend is set True, we'll suspend
        # debugging.
        self.trace_hook_suspend = False

        self.until_condition = get_option("until_condition")

        return

    def add_ignore(self, *frames_or_fns):
        """Add `frame_or_fn' to the list of functions that are not to
        be debugged"""
        for frame_or_fn in frames_or_fns:
            rc = self.ignore_filter.add(frame_or_fn)
            pass
        return rc

    def canonic(self, filename):
        """Turns `filename' into its canonic representation and returns this
        string. This allows a user to refer to a given file in one of several
        equivalent ways.

        Relative filenames need to be fully resolved, since the current working
        directory might change over the course of execution.

        If filename is enclosed in < ... >, then we assume it is
        one of the bogus internal Python names like <string> which is seen
        for example when executing "exec cmd".
        """

        if filename == "<" + filename[1:-1] + ">":
            return filename
        canonic = self.filename_cache.get(filename)
        if not canonic:
            lead_dir = filename.split(os.sep)[0]
            if lead_dir == os.curdir or lead_dir == os.pardir:
                # We may have invoked the program from a directory
                # other than where the program resides. filename is
                # relative to where the program resides. So make sure
                # to use that.
                canonic = osp.abspath(osp.join(self.main_dirname, filename))
            else:
                canonic = osp.abspath(filename)
                pass
            if not osp.isfile(canonic):
                canonic = Mclifns.search_file(
                    filename, self.search_path, self.main_dirname
                )
                # FIXME: is this is right for utter failure?
                if not canonic:
                    canonic = filename
                pass
            canonic = osp.realpath(osp.normcase(canonic))
            self.filename_cache[filename] = canonic
        if pyficache is not None:
            # removing logging can null out pyficache
            canonic = pyficache.unmap_file(canonic)

        return canonic

    def canonic_filename(self, frame):
        """Picks out the file name from `frame' and returns its
        canonic() value, a string."""
        return self.canonic(frame.f_code.co_filename)

    def filename(self, filename=None):
        """Return filename or the basename of that depending on the
        basename setting"""
        if filename is None:
            if self.debugger.mainpyfile:
                filename = self.debugger.mainpyfile
            else:
                return None
        if self.debugger.settings["basename"]:
            return osp.basename(filename)
        return filename

    def is_running(self):
        return "Running" == self.execution_status

    def is_started(self):
        """Return True if debugging is in progress."""
        return (
            tracer.is_started()
            and not self.trace_hook_suspend
            and tracer.find_hook(self.trace_dispatch)
        )

    def remove_ignore(self, frame_or_fn):
        """Remove `frame_or_fn' to the list of functions that are not to
        be debugged"""
        return self.ignore_filter.remove_include(frame_or_fn)

    def start(self, opts=None):
        """We've already created a debugger object, but here we start
        debugging in earnest. We can also turn off debugging (but have
        the hooks suspended or not) using 'stop'.

        'opts' is a hash of every known value you might want to set when
        starting the debugger. See START_OPTS of module default.
        """

        # The below is our fancy equivalent of:
        #    sys.settrace(self._trace_dispatch)
        try:
            self.trace_hook_suspend = True

            def get_option(key: str) -> Any:
                return option_set(opts, key, START_OPTS)

            add_hook_opts = get_option("add_hook_opts")

            # Has tracer been started?
            if not tracer.is_started() or get_option("force"):
                # FIXME: should filter out opts not for tracer

                tracer_start_opts = START_OPTS.copy()
                if opts:
                    tracer_start_opts.update(opts.get("tracer_start", {}))
                tracer_start_opts["trace_fn"] = self.trace_dispatch
                tracer_start_opts["add_hook_opts"] = add_hook_opts
                tracer.start(tracer_start_opts)
            elif not tracer.find_hook(self.trace_dispatch):
                tracer.add_hook(self.trace_dispatch, add_hook_opts)
                pass
            self.execution_status = "Running"
        finally:
            self.trace_hook_suspend = False
        return

    def stop(self, options=None):
        # Our version of:
        #    sys.settrace(None)
        try:
            self.trace_hook_suspend = True

            def get_option(key: str) -> Any:
                return option_set(options, key, STOP_OPTS)

            args = [self.trace_dispatch]
            remove = get_option("remove")
            if remove:
                args.append(remove)
                pass
            if tracer.is_started():
                try:
                    tracer.remove_hook(*args)
                except LookupError:
                    pass
                pass
        finally:
            self.trace_hook_suspend = False
        return

    def is_break_here(self, frame):
        filename = self.canonic(frame.f_code.co_filename)
        if "call" == self.event:
            find_name = frame.f_code.co_name
            # Could check code object or decide not to
            # The below could be done as a list comprehension, but
            # I'm feeling in Fortran mood right now.
            for fn in self.bpmgr.fnlist:
                if fn.__name__ == find_name:
                    self.current_bp = bp = self.bpmgr.fnlist[fn][0]
                    if bp.temporary:
                        msg = "temporary "
                        self.bpmgr.delete_breakpoint(bp)
                    else:
                        msg = ""
                        pass
                    self.stop_reason = f"at {msg}call breakpoint {bp.number}"
                    self.event = "brkpt"
                    return True
                pass
            pass
        if (filename, frame.f_lineno) in list(self.bpmgr.bplist.keys()):
            (bp, clear_bp) = self.bpmgr.find_bp(filename, frame.f_lineno, frame)
            if bp:
                self.current_bp = bp
                if clear_bp and bp.temporary:
                    msg = "temporary "
                    self.bpmgr.delete_breakpoint(bp)
                else:
                    msg = ""
                    pass
                self.stop_reason = f"at {msg}line breakpoint {bp.number}"
                self.event = "brkpt"
                return True
            else:
                return False
            pass
        return False

    def matches_condition(self, frame):
        # Conditional bp.
        # Ignore count applies only to those bpt hits where the
        # condition evaluates to true.
        try:
            val = eval(self.until_condition, frame.f_globals, frame.f_locals)
        except Exception:
            # if eval fails, most conservative thing is to
            # stop on breakpoint regardless of ignore count.
            # Don't delete temporary, as another hint to user.
            return False
        return val

    def is_stop_here(self, frame, event):
        """Does the magic to determine if we stop here and run a
        command processor or not. If so, return True and set
        self.stop_reason; if not, return False.

        Determining factors can be whether a breakpoint was
        encountered, whether we are stepping, next'ing, finish'ing,
        and, if so, whether there is an ignore counter.
        """

        # Add an generic event filter here?
        # FIXME TODO: Check for
        #  - thread switching (under set option)

        # Check for "next" and "finish" stopping via stop_level

        # Do we want a different line and if so,
        # do we have one?
        lineno = frame.f_lineno
        filename = frame.f_code.co_filename

        if self.different_line and event == "line":
            if self.last_lineno == lineno and self.last_filename == filename:
                return False
            pass
        self.last_lineno = lineno
        self.last_filename = filename

        if self.stop_level is not None:
            if frame and frame != self.last_frame:
                # Recompute stack_depth
                self.last_level = count_frames(frame)
                self.last_frame = frame
                pass
            if self.last_level > self.stop_level:
                return False
            elif (
                self.last_level == self.stop_level
                and self.stop_on_finish
                and event in ["return", "c_return"]
            ):
                self.stop_level = None
                self.stop_reason = "in return for 'finish' command"
                return True
            pass

        # Check for stepping
        if self._is_step_next_stop(event):
            self.stop_reason = "at a stepping statement"
            return True

        return False

    def _is_step_next_stop(self, event):
        if self.step_events and event not in self.step_events:
            return False
        if self.step_ignore == 0:
            return True
        elif self.step_ignore > 0:
            self.step_ignore -= 1
            pass
        return False

    def trace_dispatch(self, frame, event, arg):
        """A trace event occurred. Filter or pass the information to a
        specialized event processor. Note that there may be more filtering
        that goes on in the command processor (e.g. to force a
        different line). We could put that here, but since that seems
        processor-specific I think it best to distribute the checks."""

        if self.ignore_filter and self.ignore_filter.is_excluded(frame):
            return self

        self.event = event

        if self.debugger.settings["trace"]:
            print_event_set = self.debugger.settings["printset"]
            if self.event in print_event_set:
                self.processor.event_processor(frame, self.event, arg)
                pass
            pass

        if self.until_condition:
            if not self.matches_condition(frame):
                return self
            pass

        trace_event_set = self.debugger.settings["events"]
        if trace_event_set is None or self.event not in trace_event_set:
            return self

        event_filter = event_filters.get(event)

        # Update arg to let user see details of callback
        # in "info program"
        self.arg = arg

        if event_filter is not None:
            if event == "mpmath" and event_filter:
                bound_mpmath_method, call_args = arg
                mpmath_name = bound_mpmath_method.__func__.__name__
                # If we have any mpmmath event filters listed, check that
                # mpmath_name on of the names listed.
                if mpmath_name not in event_filter and event_filter:
                    return
                self.arg = (mpmath_name, bound_mpmath_method, call_args)
                pass
            elif event == "SymPy":
                sympy_function, call_args = arg
                sympy_name = sympy_function.__name__
                # If we have any SymPy event filters listed, check that
                # sympy_name on of the names listed.
                if sympy_name not in event_filter and event_filter:
                    return
                self.arg = (sympy_name, sympy_function, call_args)
            elif event == "Get":
                file_path, call_args = arg
                if file_path not in event_filter and event_filter:
                    return
            elif event == "evaluate-result":
                if frame.f_code in self.ignore_code:
                    return
                expr, _, status, orig_expr, _ = arg
                # If any of the evaluation-result filters uses a short name, then we will take the
                # short name of the original expression.
                # TODO: Think about if we should allow short names in event filters or whether we should
                # always fill those in based on $Context or $ContextPath.
                use_short = all(name.find("`") == -1 for name in event_filter)
                if event_filter and orig_expr.get_name(short=use_short) not in event_filter:
                    return
                if skip_trivial_evaluation(expr, status, orig_expr):
                    return
            elif event == "evaluate-entry":
                if frame.f_code in self.ignore_code:
                    return
                expr, _, status, orig_expr, _ = arg
                if event_filter and expr.get_name() not in event_filter:
                    return
                if skip_trivial_evaluation(expr, status, orig_expr):
                    return

            else:
                print(f"FIXME: Unhandled event {event}")
                return

        return self.processor.event_processor(frame, event, arg)

    pass


# Demo it
if __name__ == "__main__":

    class MockProcessor:
        pass

    opts = {"processor": MockProcessor()}
    dc = DebuggerCore(None, opts=opts)
    dc.step_ignore = 1
    print("dc._is_step_next_stop():", dc._is_step_next_stop("line"))
    print("dc._is_step_next_stop():", dc._is_step_next_stop("line"))
    print("dc.step_ignore:", dc.step_ignore)
    print("dc.is_started:", dc.is_started())
    print(dc.canonic("<string>"))
    print(dc.canonic(__file__))
    pass
