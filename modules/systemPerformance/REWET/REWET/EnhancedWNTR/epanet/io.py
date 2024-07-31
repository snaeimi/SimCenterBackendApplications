"""The wntrfr.epanet.io module contains methods for reading/writing EPANET input and output files.

.. rubric:: Contents

.. autosummary::

    InpFile
    BinFile
s
"""  # noqa: E501

import datetime
import difflib
import logging
import os
import re
import sys
import warnings
from collections import OrderedDict

import numpy as np
import pandas as pd
import wntrfr
import wntrfr.network
from wntrfr.epanet.util import (
    EN,
    FlowUnits,
    HydParam,
    MassUnits,
    MixType,
    PressureUnits,
    QualParam,
    QualType,
    ResultType,
    StatisticsType,
    from_si,
    to_si,
)
from wntrfr.network.base import Link
from wntrfr.network.controls import (
    AndCondition,
    Comparison,
    Control,
    ControlAction,
    OrCondition,
    Rule,
    SimTimeCondition,
    TimeOfDayCondition,
    ValueCondition,
    _ControlType,
)
from wntrfr.network.elements import Junction, Pipe, Pump, Tank, Valve
from wntrfr.network.model import (
    LinkStatus,
    WaterNetworkModel,
)

# from .time_utils import run_lineprofile  # noqa: ERA001
sys_default_enc = sys.getdefaultencoding()


logger = logging.getLogger(__name__)

_INP_SECTIONS = [
    '[OPTIONS]',
    '[TITLE]',
    '[JUNCTIONS]',
    '[RESERVOIRS]',
    '[TANKS]',
    '[PIPES]',
    '[PUMPS]',
    '[VALVES]',
    '[EMITTERS]',
    '[CURVES]',
    '[PATTERNS]',
    '[ENERGY]',
    '[STATUS]',
    '[CONTROLS]',
    '[RULES]',
    '[DEMANDS]',
    '[QUALITY]',
    '[REACTIONS]',
    '[SOURCES]',
    '[MIXING]',
    '[TIMES]',
    '[REPORT]',
    '[COORDINATES]',
    '[VERTICES]',
    '[LABELS]',
    '[BACKDROP]',
    '[TAGS]',
]

_JUNC_ENTRY = ' {name:20} {elev:15.11g} {dem:15.11g} {pat:24} {com:>3s}\n'
_JUNC_LABEL = '{:21} {:>12s} {:>12s} {:24}\n'

_RES_ENTRY = ' {name:20s} {head:15.11g} {pat:>24s} {com:>3s}\n'
_RES_LABEL = '{:21s} {:>20s} {:>24s}\n'

_TANK_ENTRY = ' {name:20s} {elev:15.11g} {initlev:15.11g} {minlev:15.11g} {maxlev:15.11g} {diam:15.11g} {minvol:15.11g} {curve:20s} {overflow:20s} {com:>3s}\n'  # noqa: E501
_TANK_LABEL = (
    '{:21s} {:>20s} {:>20s} {:>20s} {:>20s} {:>20s} {:>20s} {:20s} {:20s}\n'
)

_PIPE_ENTRY = ' {name:20s} {node1:20s} {node2:20s} {len:15.11g} {diam:15.11g} {rough:15.11g} {mloss:15.11g} {status:>20s} {com:>3s}\n'  # noqa: E501
_PIPE_LABEL = '{:21s} {:20s} {:20s} {:>20s} {:>20s} {:>20s} {:>20s} {:>20s}\n'

_PUMP_ENTRY = (
    ' {name:20s} {node1:20s} {node2:20s} {ptype:8s} {params:20s} {com:>3s}\n'
)
_PUMP_LABEL = '{:21s} {:20s} {:20s} {:20s}\n'

_VALVE_ENTRY = ' {name:20s} {node1:20s} {node2:20s} {diam:15.11g} {vtype:4s} {set:15.11g} {mloss:15.11g} {com:>3s}\n'  # noqa: E501
_GPV_ENTRY = ' {name:20s} {node1:20s} {node2:20s} {diam:15.11g} {vtype:4s} {set:20s} {mloss:15.11g} {com:>3s}\n'  # noqa: E501
_VALVE_LABEL = '{:21s} {:20s} {:20s} {:>20s} {:4s} {:>20s} {:>20s}\n'

_CURVE_ENTRY = ' {name:10s} {x:12f} {y:12f} {com:>3s}\n'
_CURVE_LABEL = '{:11s} {:12s} {:12s}\n'


def _split_line(line):  # noqa: ANN001, ANN202
    _vc = line.split(';', 1)
    _cmnt = None
    _vals = None
    if len(_vc) == 0:
        pass
    elif len(_vc) == 1:
        _vals = _vc[0].split()
    elif _vc[0] == '':
        _cmnt = _vc[1]
    else:
        _vals = _vc[0].split()
        _cmnt = _vc[1]
    return _vals, _cmnt


def _is_number(s):  # noqa: ANN001, ANN202, D417
    """Checks if input is a number

    Parameters
    ----------
    s : anything

    Returns
    -------
    bool
        Input is a number

    """  # noqa: D400, D401, D415
    try:
        float(s)
        return True  # noqa: TRY300
    except ValueError:
        return False


def _str_time_to_sec(s):  # noqa: ANN001, ANN202
    """Converts EPANET time format to seconds.

    Parameters
    ----------
    s : string
        EPANET time string. Options are 'HH:MM:SS', 'HH:MM', 'HH'


    Returns
    -------
    int
        Integer value of time in seconds.

    """  # noqa: D401
    pattern1 = re.compile(r'^(\d+):(\d+):(\d+)$')
    time_tuple = pattern1.search(s)
    if bool(time_tuple):
        return (
            int(time_tuple.groups()[0]) * 60 * 60
            + int(time_tuple.groups()[1]) * 60
            + int(round(float(time_tuple.groups()[2])))
        )
    else:  # noqa: RET505
        pattern2 = re.compile(r'^(\d+):(\d+)$')
        time_tuple = pattern2.search(s)
        if bool(time_tuple):
            return (
                int(time_tuple.groups()[0]) * 60 * 60
                + int(time_tuple.groups()[1]) * 60
            )
        else:  # noqa: RET505
            pattern3 = re.compile(r'^(\d+)$')
            time_tuple = pattern3.search(s)
            if bool(time_tuple):
                return int(time_tuple.groups()[0]) * 60 * 60
            else:  # noqa: RET505
                raise RuntimeError('Time format in ' 'INP file not recognized. ')  # noqa: EM101, TRY003


def _clock_time_to_sec(s, am_pm):  # noqa: ANN001, ANN202, C901, D417, PLR0912
    """Converts EPANET clocktime format to seconds.

    Parameters
    ----------
    s : string
        EPANET time string. Options are 'HH:MM:SS', 'HH:MM', HH'

    am : string
        options are AM or PM


    Returns
    -------
    int
        Integer value of time in seconds

    """  # noqa: D401
    if am_pm.upper() == 'AM':
        am = True
    elif am_pm.upper() == 'PM':
        am = False
    else:
        raise RuntimeError('am_pm option not recognized; options are AM or PM')  # noqa: EM101, TRY003

    pattern1 = re.compile(r'^(\d+):(\d+):(\d+)$')
    time_tuple = pattern1.search(s)
    if bool(time_tuple):
        time_sec = (
            int(time_tuple.groups()[0]) * 60 * 60
            + int(time_tuple.groups()[1]) * 60
            + int(round(float(time_tuple.groups()[2])))
        )
        if s.startswith('12'):
            time_sec -= 3600 * 12
        if not am:
            if time_sec >= 3600 * 12:
                raise RuntimeError(  # noqa: TRY003
                    'Cannot specify am/pm for times greater than 12:00:00'  # noqa: EM101
                )
            time_sec += 3600 * 12
        return time_sec
    else:  # noqa: RET505
        pattern2 = re.compile(r'^(\d+):(\d+)$')
        time_tuple = pattern2.search(s)
        if bool(time_tuple):
            time_sec = (
                int(time_tuple.groups()[0]) * 60 * 60
                + int(time_tuple.groups()[1]) * 60
            )
            if s.startswith('12'):
                time_sec -= 3600 * 12
            if not am:
                if time_sec >= 3600 * 12:
                    raise RuntimeError(  # noqa: TRY003
                        'Cannot specify am/pm for times greater than 12:00:00'  # noqa: EM101
                    )
                time_sec += 3600 * 12
            return time_sec
        else:  # noqa: RET505
            pattern3 = re.compile(r'^(\d+)$')
            time_tuple = pattern3.search(s)
            if bool(time_tuple):
                time_sec = int(time_tuple.groups()[0]) * 60 * 60
                if s.startswith('12'):
                    time_sec -= 3600 * 12
                if not am:
                    if time_sec >= 3600 * 12:
                        raise RuntimeError(  # noqa: TRY003
                            'Cannot specify am/pm for times greater than 12:00:00'  # noqa: EM101
                        )
                    time_sec += 3600 * 12
                return time_sec
            else:  # noqa: RET505
                raise RuntimeError('Time format in ' 'INP file not recognized. ')  # noqa: EM101, TRY003


def _sec_to_string(sec):  # noqa: ANN001, ANN202
    hours = int(sec / 3600.0)
    sec -= hours * 3600
    mm = int(sec / 60.0)
    sec -= mm * 60
    return (hours, mm, int(sec))


class InpFile:
    """EPANET INP file reader and writer class.

    This class provides read and write functionality for EPANET INP files.
    The EPANET Users Manual provides full documentation for the INP file format.
    """

    def __init__(self):  # noqa: ANN204, D107
        self.sections = OrderedDict()
        for sec in _INP_SECTIONS:
            self.sections[sec] = []
        self.mass_units = None
        self.flow_units = None
        self.top_comments = []
        self.curves = OrderedDict()

    def read(self, inp_files, wn=None):  # noqa: ANN001, ANN201, C901, PLR0912, PLR0915
        """Read an EPANET INP file and load data into a water network model object.
        Both EPANET 2.0 and EPANET 2.2 INP file options are recognized and handled.

        Parameters
        ----------
        inp_files : str or list
            An EPANET INP input file or list of INP files to be combined
        wn : WaterNetworkModel, optional
            An optional network model to append onto; by default a new model is created.

        Returns
        -------
        :class:`~wntrfr.network.model.WaterNetworkModel`
            A water network model object

        """  # noqa: E501, D205
        if wn is None:
            wn = WaterNetworkModel()
        self.wn = wn
        if not isinstance(inp_files, list):
            inp_files = [inp_files]
        wn.name = inp_files[0]

        self.curves = OrderedDict()
        self.top_comments = []
        self.sections = OrderedDict()
        for sec in _INP_SECTIONS:
            self.sections[sec] = []
        self.mass_units = None
        self.flow_units = None

        for filename in inp_files:
            section = None
            lnum = 0
            edata = {'fname': filename}
            with open(filename, encoding='utf-8') as f:  # noqa: PTH123
                for line in f:
                    lnum += 1
                    edata['lnum'] = lnum
                    line = line.strip()  # noqa: PLW2901
                    nwords = len(line.split())
                    if len(line) == 0 or nwords == 0:
                        # Blank line
                        continue
                    elif line.startswith('['):  # noqa: RET507
                        vals = line.split(None, 1)
                        sec = vals[0].upper()
                        # Add handlers to deal with extra 'S'es (or missing 'S'es) in INP file  # noqa: E501
                        if sec not in _INP_SECTIONS:
                            trsec = sec.replace(']', 'S]')
                            if trsec in _INP_SECTIONS:
                                sec = trsec
                        if sec not in _INP_SECTIONS:
                            trsec = sec.replace('S]', ']')
                            if trsec in _INP_SECTIONS:
                                sec = trsec
                        edata['sec'] = sec
                        if sec in _INP_SECTIONS:
                            section = sec
                            # logger.info('%(fname)s:%(lnum)-6d %(sec)13s section found' % edata)  # noqa: ERA001, E501
                            continue
                        elif sec == '[END]':  # noqa: RET507
                            # logger.info('%(fname)s:%(lnum)-6d %(sec)13s end of file found' % edata)  # noqa: ERA001, E501
                            section = None
                            break
                        else:
                            raise RuntimeError(
                                '%(fname)s:%(lnum)d: Invalid section "%(sec)s"'
                                % edata
                            )
                    elif section is None and line.startswith(';'):
                        self.top_comments.append(line[1:])
                        continue
                    elif section is None:
                        logger.debug('Found confusing line: %s', repr(line))
                        raise RuntimeError(
                            '%(fname)s:%(lnum)d: Non-comment outside of valid section!'  # noqa: E501
                            % edata
                        )
                    # We have text, and we are in a section
                    self.sections[section].append((lnum, line))

        # Parse each of the sections
        # The order of operations is important as certain things require prior knowledge  # noqa: E501

        ### OPTIONS
        self._read_options()

        ### TIMES
        self._read_times()

        ### CURVES
        self._read_curves()

        ### PATTERNS
        self._read_patterns()

        ### JUNCTIONS
        self._read_junctions()

        ### RESERVOIRS
        self._read_reservoirs()

        ### TANKS
        self._read_tanks()

        ### PIPES
        self._read_pipes()

        ### PUMPS
        self._read_pumps()

        ### VALVES
        self._read_valves()

        ### COORDINATES
        self._read_coordinates()

        ### SOURCES
        self._read_sources()

        ### STATUS
        self._read_status()

        ### CONTROLS
        self._read_controls()

        ### RULES
        self._read_rules()

        ### REACTIONS
        self._read_reactions()

        ### TITLE
        self._read_title()

        ### ENERGY
        self._read_energy()

        ### DEMANDS
        self._read_demands()

        ### EMITTERS
        self._read_emitters()

        ### QUALITY
        self._read_quality()

        self._read_mixing()
        self._read_report()
        self._read_vertices()
        self._read_labels()

        ### Parse Backdrop
        self._read_backdrop()

        ### TAGS
        self._read_tags()

        # Set the _inpfile io data inside the water network, so it is saved somewhere
        wn._inpfile = self  # noqa: SLF001

        ### Finish tags
        self._read_end()

        return self.wn

    def write(self, filename, wn, units=None, version=2.2, force_coordinates=False):  # noqa: ANN001, ANN201, FBT002, D417
        """Write a water network model into an EPANET INP file.

        .. note::

            Please note that by default, an EPANET 2.2 formatted file is written by wntrfr. An INP file
            with version 2.2 options *will not* work with EPANET 2.0 (neither command line nor GUI).
            By default, WNTR will use the EPANET 2.2 toolkit.


        Parameters
        ----------
        filename : str
            Name of the EPANET INP file.
        units : str, int or FlowUnits
            Name of the units for the EPANET INP file to be written in.
        version : float, {2.0, **2.2**}
            Defaults to 2.2; use 2.0 to guarantee backward compatability, but this will turn off PDD mode
            and supress the writing of other EPANET 2.2-specific options. If PDD mode is specified, a
            warning will be issued.
        force_coordinates : bool
            This only applies if `self.options.graphics.map_filename` is not `None`,
            and will force the COORDINATES section to be written even if a MAP file is
            provided. False by default, but coordinates **are** written by default since
            the MAP file is `None` by default.

        """  # noqa: E501
        if not isinstance(wn, WaterNetworkModel):
            raise ValueError('Must pass a WaterNetworkModel object')  # noqa: EM101, TRY003, TRY004
        if units is not None and isinstance(units, str):
            units = units.upper()
            self.flow_units = FlowUnits[units]
        elif units is not None and isinstance(units, FlowUnits):
            self.flow_units = units
        elif units is not None and isinstance(units, int):
            self.flow_units = FlowUnits(units)
        elif self.flow_units is not None:
            self.flow_units = self.flow_units
        elif isinstance(wn.options.hydraulic.inpfile_units, str):
            units = wn.options.hydraulic.inpfile_units.upper()
            self.flow_units = FlowUnits[units]
        else:
            self.flow_units = FlowUnits.GPM
        if self.mass_units is None:
            self.mass_units = MassUnits.mg
        with open(filename, 'wb') as f:  # noqa: PTH123
            self._write_title(f, wn)
            self._write_junctions(f, wn)
            self._write_reservoirs(f, wn)
            self._write_tanks(f, wn, version=version)
            self._write_pipes(f, wn)
            self._write_pumps(f, wn)
            self._write_valves(f, wn)

            self._write_tags(f, wn)
            self._write_demands(f, wn)
            self._write_status(f, wn)
            self._write_patterns(f, wn)
            self._write_curves(f, wn)
            self._write_controls(f, wn)
            self._write_rules(f, wn)
            self._write_energy(f, wn)
            self._write_emitters(f, wn)

            self._write_quality(f, wn)
            self._write_sources(f, wn)
            self._write_reactions(f, wn)
            self._write_mixing(f, wn)

            self._write_times(f, wn)
            self._write_report(f, wn)
            self._write_options(f, wn, version=version)

            if wn.options.graphics.map_filename is None or force_coordinates is True:
                self._write_coordinates(f, wn)
            self._write_vertices(f, wn)
            self._write_labels(f, wn)
            self._write_backdrop(f, wn)

            self._write_end(f, wn)

    ### Network Components

    def _read_title(self):  # noqa: ANN202
        lines = []
        for lnum, line in self.sections['[TITLE]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            lines.append(line)
        self.wn.title = lines

    def _write_title(self, f, wn):  # noqa: ANN001, ANN202
        if wn.name is not None:
            f.write(f'; Filename: {wn.name}\n'.encode(sys_default_enc))
            f.write(
                f'; WNTR: {wntrfr.__version__}\n; Created: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n'.encode(  # noqa: DTZ005, E501
                    sys_default_enc
                )
            )
        f.write('[TITLE]\n'.encode(sys_default_enc))
        if hasattr(wn, 'title'):
            for line in wn.title:
                f.write(f'{line}\n'.encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_junctions(self):  # noqa: ANN202
        #        try:  # noqa: ERA001
        for lnum, line in self.sections['[JUNCTIONS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if len(current) > 3:  # noqa: PLR2004
                pat = current[3]
            elif self.wn.options.hydraulic.pattern:
                pat = self.wn.options.hydraulic.pattern
            else:
                pat = self.wn.patterns.default_pattern
            base_demand = 0.0
            if len(current) > 2:  # noqa: PLR2004
                base_demand = to_si(
                    self.flow_units, float(current[2]), HydParam.Demand
                )
            self.wn.add_junction(
                current[0],
                base_demand,
                pat,
                to_si(self.flow_units, float(current[1]), HydParam.Elevation),
                demand_category=None,
            )

    #        except Exception as e:  # noqa: ERA001
    #            print(line)  # noqa: ERA001
    #            raise e

    def _write_junctions(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[JUNCTIONS]\n'.encode(sys_default_enc))
        f.write(
            _JUNC_LABEL.format(';ID', 'Elevation', 'Demand', 'Pattern').encode(
                sys_default_enc
            )
        )
        nnames = list(wn.junction_name_list)
        # nnames.sort()  # noqa: ERA001
        for junction_name in nnames:
            junction = wn.nodes[junction_name]

            if junction._is_isolated == True:  # sina added this  # noqa: SLF001, E712
                continue

            if junction.demand_timeseries_list:
                base_demands = junction.demand_timeseries_list.base_demand_list()
                demand_patterns = junction.demand_timeseries_list.pattern_list()
                if base_demands:  # noqa: SIM108
                    base_demand = base_demands[0]
                else:
                    base_demand = 0.0
                if demand_patterns:
                    if demand_patterns[0] == wn.options.hydraulic.pattern:
                        demand_pattern = None
                    else:
                        demand_pattern = demand_patterns[0]
                else:
                    demand_pattern = None
            else:
                base_demand = 0.0
                demand_pattern = None
            E = {  # noqa: N806
                'name': junction_name,
                'elev': from_si(
                    self.flow_units, junction.elevation, HydParam.Elevation
                ),
                'dem': from_si(self.flow_units, base_demand, HydParam.Demand),
                'pat': '',
                'com': ';',
            }
            if demand_pattern is not None:
                E['pat'] = str(demand_pattern)
            f.write(_JUNC_ENTRY.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_reservoirs(self):  # noqa: ANN202
        for lnum, line in self.sections['[RESERVOIRS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if len(current) == 2:  # noqa: PLR2004
                self.wn.add_reservoir(
                    current[0],
                    to_si(
                        self.flow_units, float(current[1]), HydParam.HydraulicHead
                    ),
                )
            else:
                self.wn.add_reservoir(
                    current[0],
                    to_si(
                        self.flow_units, float(current[1]), HydParam.HydraulicHead
                    ),
                    current[2],
                )

    def _write_reservoirs(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[RESERVOIRS]\n'.encode(sys_default_enc))
        f.write(_RES_LABEL.format(';ID', 'Head', 'Pattern').encode(sys_default_enc))
        nnames = list(wn.reservoir_name_list)
        # nnames.sort()  # noqa: ERA001
        for reservoir_name in nnames:
            reservoir = wn.nodes[reservoir_name]

            if reservoir._is_isolated == True:  # sina added this  # noqa: SLF001, E712
                continue

            E = {  # noqa: N806
                'name': reservoir_name,
                'head': from_si(
                    self.flow_units,
                    reservoir.head_timeseries.base_value,
                    HydParam.HydraulicHead,
                ),
                'com': ';',
            }
            if reservoir.head_timeseries.pattern is None:
                E['pat'] = ''
            else:
                E['pat'] = reservoir.head_timeseries.pattern.name
            f.write(_RES_ENTRY.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_tanks(self):  # noqa: ANN202
        for lnum, line in self.sections['[TANKS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            volume = None
            if len(current) >= 8:  # Volume curve provided  # noqa: PLR2004
                volume = float(current[6])
                curve_name = current[7]
                if curve_name == '*':
                    curve_name = None
                else:
                    curve_points = []
                    for point in self.curves[curve_name]:
                        x = to_si(self.flow_units, point[0], HydParam.Length)
                        y = to_si(self.flow_units, point[1], HydParam.Volume)
                        curve_points.append((x, y))
                    self.wn.add_curve(curve_name, 'VOLUME', curve_points)
                #                curve = self.wn.get_curve(curve_name)  # noqa: ERA001
                if len(current) == 9:  # noqa: SIM108, PLR2004
                    overflow = current[8]
                else:
                    overflow = False
            elif len(current) == 7:  # noqa: PLR2004
                curve_name = None
                overflow = False
                volume = float(current[6])
            elif len(current) == 6:  # noqa: PLR2004
                curve_name = None
                overflow = False
                volume = 0.0
            else:
                raise RuntimeError('Tank entry format not recognized.')  # noqa: EM101, TRY003
            self.wn.add_tank(
                current[0],
                to_si(self.flow_units, float(current[1]), HydParam.Elevation),
                to_si(self.flow_units, float(current[2]), HydParam.Length),
                to_si(self.flow_units, float(current[3]), HydParam.Length),
                to_si(self.flow_units, float(current[4]), HydParam.Length),
                to_si(self.flow_units, float(current[5]), HydParam.TankDiameter),
                to_si(self.flow_units, float(volume), HydParam.Volume),
                curve_name,
                overflow,
            )

    def _write_tanks(self, f, wn, version=2.2):  # noqa: ANN001, ANN202
        f.write('[TANKS]\n'.encode(sys_default_enc))
        if version != 2.2:  # noqa: PLR2004
            f.write(
                _TANK_LABEL.format(
                    ';ID',
                    'Elevation',
                    'Init Level',
                    'Min Level',
                    'Max Level',
                    'Diameter',
                    'Min Volume',
                    'Volume Curve',
                    '',
                ).encode(sys_default_enc)
            )
        else:
            f.write(
                _TANK_LABEL.format(
                    ';ID',
                    'Elevation',
                    'Init Level',
                    'Min Level',
                    'Max Level',
                    'Diameter',
                    'Min Volume',
                    'Volume Curve',
                    'Overflow',
                ).encode(sys_default_enc)
            )
        nnames = list(wn.tank_name_list)
        # nnames.sort()  # noqa: ERA001
        for tank_name in nnames:
            tank = wn.nodes[tank_name]

            if tank._is_isolated == True:  # sina added this  # noqa: SLF001, E712
                continue

            E = {  # noqa: N806
                'name': tank_name,
                'elev': from_si(self.flow_units, tank.elevation, HydParam.Elevation),
                'initlev': from_si(
                    self.flow_units, tank.init_level, HydParam.HydraulicHead
                ),
                'minlev': from_si(
                    self.flow_units, tank.min_level, HydParam.HydraulicHead
                ),
                'maxlev': from_si(
                    self.flow_units, tank.max_level, HydParam.HydraulicHead
                ),
                'diam': from_si(
                    self.flow_units, tank.diameter, HydParam.TankDiameter
                ),
                'minvol': from_si(self.flow_units, tank.min_vol, HydParam.Volume),
                'curve': '',
                'overflow': '',
                'com': ';',
            }
            if tank.vol_curve is not None:
                E['curve'] = tank.vol_curve.name
            if version == 2.2:  # noqa: SIM102, PLR2004
                if tank.overflow:
                    E['overflow'] = 'YES'
                    if tank.vol_curve is None:
                        E['curve'] = '*'
            f.write(_TANK_ENTRY.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_pipes(self):  # noqa: ANN202
        for lnum, line in self.sections['[PIPES]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if len(current) == 8:  # noqa: PLR2004
                minor_loss = float(current[6])
                if current[7].upper() == 'CV':
                    link_status = LinkStatus.Open
                    check_valve = True
                else:
                    link_status = LinkStatus[current[7].upper()]
                    check_valve = False
            elif len(current) == 7:  # noqa: PLR2004
                minor_loss = float(current[6])
                link_status = LinkStatus.Open
                check_valve = False
            elif len(current) == 6:  # noqa: PLR2004
                minor_loss = 0.0
                link_status = LinkStatus.Open
                check_valve = False

            self.wn.add_pipe(
                current[0],
                current[1],
                current[2],
                to_si(self.flow_units, float(current[3]), HydParam.Length),
                to_si(self.flow_units, float(current[4]), HydParam.PipeDiameter),
                float(current[5]),
                minor_loss,
                link_status,
                check_valve,
            )

    def _write_pipes(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[PIPES]\n'.encode(sys_default_enc))
        f.write(
            _PIPE_LABEL.format(
                ';ID',
                'Node1',
                'Node2',
                'Length',
                'Diameter',
                'Roughness',
                'Minor Loss',
                'Status',
            ).encode(sys_default_enc)
        )
        lnames = list(wn.pipe_name_list)
        # lnames.sort()  # noqa: ERA001
        for pipe_name in lnames:
            pipe = wn.links[pipe_name]

            if pipe._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            E = {  # noqa: N806
                'name': pipe_name,
                'node1': pipe.start_node_name,
                'node2': pipe.end_node_name,
                'len': from_si(self.flow_units, pipe.length, HydParam.Length),
                'diam': from_si(
                    self.flow_units, pipe.diameter, HydParam.PipeDiameter
                ),
                'rough': pipe.roughness,
                'mloss': pipe.minor_loss,
                'status': str(pipe.initial_status),
                'com': ';',
            }
            if pipe.check_valve:
                E['status'] = 'CV'
            f.write(_PIPE_ENTRY.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_pumps(self):  # noqa: ANN202, C901
        def create_curve(curve_name):  # noqa: ANN001, ANN202
            curve_points = []
            if (
                curve_name not in self.wn.curve_name_list
                or self.wn.get_curve(curve_name) is None
            ):
                for point in self.curves[curve_name]:
                    x = to_si(self.flow_units, point[0], HydParam.Flow)
                    y = to_si(self.flow_units, point[1], HydParam.HydraulicHead)
                    curve_points.append((x, y))
                self.wn.add_curve(curve_name, 'HEAD', curve_points)
            curve = self.wn.get_curve(curve_name)
            return curve  # noqa: RET504

        for lnum, line in self.sections['[PUMPS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue

            pump_type = None
            value = None
            speed = None
            pattern = None

            for i in range(3, len(current), 2):
                if current[i].upper() == 'HEAD':
                    #                    assert pump_type is None, 'In [PUMPS] entry, specify either HEAD or POWER once.'  # noqa: ERA001, E501
                    pump_type = 'HEAD'
                    value = create_curve(current[i + 1]).name
                elif current[i].upper() == 'POWER':
                    #                    assert pump_type is None, 'In [PUMPS] entry, specify either HEAD or POWER once.'  # noqa: ERA001, E501
                    pump_type = 'POWER'
                    value = to_si(
                        self.flow_units, float(current[i + 1]), HydParam.Power
                    )
                elif current[i].upper() == 'SPEED':
                    #                    assert speed is None, 'In [PUMPS] entry, SPEED may only be specified once.'  # noqa: ERA001, E501
                    speed = float(current[i + 1])
                elif current[i].upper() == 'PATTERN':
                    #                    assert pattern is None, 'In [PUMPS] entry, PATTERN may only be specified once.'  # noqa: ERA001, E501
                    pattern = self.wn.get_pattern(current[i + 1]).name
                else:
                    raise RuntimeError('Pump keyword in inp file not recognized.')  # noqa: EM101, TRY003

            if speed is None:
                speed = 1.0

            if pump_type is None:
                raise RuntimeError(  # noqa: TRY003
                    'Either head curve id or pump power must be specified for all pumps.'  # noqa: EM101, E501
                )
            self.wn.add_pump(
                current[0], current[1], current[2], pump_type, value, speed, pattern
            )

    def _write_pumps(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[PUMPS]\n'.encode(sys_default_enc))
        f.write(
            _PUMP_LABEL.format(';ID', 'Node1', 'Node2', 'Properties').encode(
                sys_default_enc
            )
        )
        lnames = list(wn.pump_name_list)
        # lnames.sort()  # noqa: ERA001
        for pump_name in lnames:
            pump = wn.links[pump_name]

            if pump._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            E = {  # noqa: N806
                'name': pump_name,
                'node1': pump.start_node_name,
                'node2': pump.end_node_name,
                'ptype': pump.pump_type,
                'params': '',
                #                 'speed_keyword': 'SPEED',  # noqa: ERA001
                #                 'speed': pump.speed_timeseries.base_value,  # noqa: ERA001
                'com': ';',
            }
            if pump.pump_type == 'HEAD':
                E['params'] = pump.pump_curve_name
            elif pump.pump_type == 'POWER':
                E['params'] = str(
                    from_si(self.flow_units, pump.power, HydParam.Power)
                )
            else:
                raise RuntimeError('Only head or power info is supported of pumps.')  # noqa: EM101, TRY003
            tmp_entry = _PUMP_ENTRY
            if pump.speed_timeseries.base_value != 1:
                E['speed_keyword'] = 'SPEED'
                E['speed'] = pump.speed_timeseries.base_value
                tmp_entry = (
                    tmp_entry.rstrip('\n').rstrip('}').rstrip('com:>3s').rstrip(' {')
                    + ' {speed_keyword:8s} {speed:15.11g} {com:>3s}\n'
                )
            if pump.speed_timeseries.pattern is not None:
                tmp_entry = (
                    tmp_entry.rstrip('\n').rstrip('}').rstrip('com:>3s').rstrip(' {')
                    + ' {pattern_keyword:10s} {pattern:20s} {com:>3s}\n'
                )
                E['pattern_keyword'] = 'PATTERN'
                E['pattern'] = pump.speed_timeseries.pattern.name
            f.write(tmp_entry.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_valves(self):  # noqa: ANN202
        for lnum, line in self.sections['[VALVES]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if len(current) == 6:  # noqa: PLR2004
                current.append(0.0)
            elif len(current) != 7:  # noqa: PLR2004
                raise RuntimeError(  # noqa: TRY003
                    'The [VALVES] section of an INP file must have 6 or 7 entries.'  # noqa: EM101
                )
            valve_type = current[4].upper()
            if valve_type in ['PRV', 'PSV', 'PBV']:
                valve_set = to_si(
                    self.flow_units, float(current[5]), HydParam.Pressure
                )
            elif valve_type == 'FCV':
                valve_set = to_si(self.flow_units, float(current[5]), HydParam.Flow)
            elif valve_type == 'TCV':
                valve_set = float(current[5])
            elif valve_type == 'GPV':
                curve_name = current[5]
                curve_points = []
                for point in self.curves[curve_name]:
                    x = to_si(self.flow_units, point[0], HydParam.Flow)
                    y = to_si(self.flow_units, point[1], HydParam.HeadLoss)
                    curve_points.append((x, y))
                self.wn.add_curve(curve_name, 'HEADLOSS', curve_points)
                valve_set = curve_name
            else:
                raise RuntimeError('VALVE type "%s" unrecognized' % valve_type)  # noqa: UP031
            self.wn.add_valve(
                current[0],
                current[1],
                current[2],
                to_si(self.flow_units, float(current[3]), HydParam.PipeDiameter),
                current[4].upper(),
                float(current[6]),
                valve_set,
            )

    def _write_valves(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[VALVES]\n'.encode(sys_default_enc))
        f.write(
            _VALVE_LABEL.format(
                ';ID', 'Node1', 'Node2', 'Diameter', 'Type', 'Setting', 'Minor Loss'
            ).encode(sys_default_enc)
        )
        lnames = list(wn.valve_name_list)
        # lnames.sort()  # noqa: ERA001
        for valve_name in lnames:
            valve = wn.links[valve_name]

            if valve._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            E = {  # noqa: N806
                'name': valve_name,
                'node1': valve.start_node_name,
                'node2': valve.end_node_name,
                'diam': from_si(
                    self.flow_units, valve.diameter, HydParam.PipeDiameter
                ),
                'vtype': valve.valve_type,
                'set': valve.initial_setting,
                'mloss': valve.minor_loss,
                'com': ';',
            }
            valve_type = valve.valve_type
            formatter = _VALVE_ENTRY
            if valve_type in ['PRV', 'PSV', 'PBV']:
                valve_set = from_si(
                    self.flow_units, valve.initial_setting, HydParam.Pressure
                )
            elif valve_type == 'FCV':
                valve_set = from_si(
                    self.flow_units, valve.initial_setting, HydParam.Flow
                )
            elif valve_type == 'TCV':
                valve_set = valve.initial_setting
            elif valve_type == 'GPV':
                valve_set = valve.headloss_curve_name
                formatter = _GPV_ENTRY
            E['set'] = valve_set
            f.write(formatter.format(**E).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_emitters(self):  # noqa: ANN202
        for lnum, line in self.sections[  # noqa: B007
            '[EMITTERS]'
        ]:  # Private attribute on junctions
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            junction = self.wn.get_node(current[0])
            junction.emitter_coefficient = to_si(
                self.flow_units, float(current[1]), HydParam.EmitterCoeff
            )

    def _write_emitters(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[EMITTERS]\n'.encode(sys_default_enc))
        entry = '{:10s} {:10s}\n'
        label = '{:10s} {:10s}\n'
        f.write(label.format(';ID', 'Flow coefficient').encode(sys_default_enc))
        njunctions = list(wn.junction_name_list)
        # njunctions.sort()  # noqa: ERA001
        for junction_name in njunctions:
            junction = wn.nodes[junction_name]

            if junction._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            if junction.emitter_coefficient:
                val = from_si(
                    self.flow_units,
                    junction.emitter_coefficient,
                    HydParam.EmitterCoeff,
                )
                f.write(
                    entry.format(junction_name, str(val)).encode(sys_default_enc)
                )
        f.write('\n'.encode(sys_default_enc))

    ### System Operation

    def _read_curves(self):  # noqa: ANN202
        for lnum, line in self.sections['[CURVES]']:  # noqa: B007
            # It should be noted carefully that these lines are never directly
            # applied to the WaterNetworkModel object. Because different curve
            # types are treated differently, each of the curves are converted
            # the first time they are used, and this is used to build up a
            # dictionary for those conversions to take place.
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            curve_name = current[0]
            if curve_name not in self.curves:
                self.curves[curve_name] = []
            self.curves[curve_name].append((float(current[1]), float(current[2])))
            self.wn.curves[curve_name] = None

    def _write_curves(self, f, wn):  # noqa: ANN001, ANN202, C901
        f.write('[CURVES]\n'.encode(sys_default_enc))
        f.write(
            _CURVE_LABEL.format(';ID', 'X-Value', 'Y-Value').encode(sys_default_enc)
        )
        curves = list(wn.curve_name_list)
        # curves.sort()  # noqa: ERA001
        for curve_name in curves:
            curve = wn.get_curve(curve_name)
            if curve.curve_type == 'VOLUME':
                f.write(f';VOLUME: {curve_name}\n'.encode(sys_default_enc))
                for point in curve.points:
                    x = from_si(self.flow_units, point[0], HydParam.Length)
                    y = from_si(self.flow_units, point[1], HydParam.Volume)
                    f.write(
                        _CURVE_ENTRY.format(
                            name=curve_name, x=x, y=y, com=';'
                        ).encode(sys_default_enc)
                    )
            elif curve.curve_type == 'HEAD':
                f.write(f';PUMP: {curve_name}\n'.encode(sys_default_enc))
                for point in curve.points:
                    x = from_si(self.flow_units, point[0], HydParam.Flow)
                    y = from_si(self.flow_units, point[1], HydParam.HydraulicHead)
                    f.write(
                        _CURVE_ENTRY.format(
                            name=curve_name, x=x, y=y, com=';'
                        ).encode(sys_default_enc)
                    )
            elif curve.curve_type == 'EFFICIENCY':
                f.write(f';EFFICIENCY: {curve_name}\n'.encode(sys_default_enc))
                for point in curve.points:
                    x = from_si(self.flow_units, point[0], HydParam.Flow)
                    y = point[1]
                    f.write(
                        _CURVE_ENTRY.format(
                            name=curve_name, x=x, y=y, com=';'
                        ).encode(sys_default_enc)
                    )
            elif curve.curve_type == 'HEADLOSS':
                f.write(f';HEADLOSS: {curve_name}\n'.encode(sys_default_enc))
                for point in curve.points:
                    x = from_si(self.flow_units, point[0], HydParam.Flow)
                    y = from_si(self.flow_units, point[1], HydParam.HeadLoss)
                    f.write(
                        _CURVE_ENTRY.format(
                            name=curve_name, x=x, y=y, com=';'
                        ).encode(sys_default_enc)
                    )
            else:
                f.write(f';UNKNOWN: {curve_name}\n'.encode(sys_default_enc))
                for point in curve.points:
                    x = point[0]
                    y = point[1]
                    f.write(
                        _CURVE_ENTRY.format(
                            name=curve_name, x=x, y=y, com=';'
                        ).encode(sys_default_enc)
                    )
            f.write('\n'.encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_patterns(self):  # noqa: ANN202
        _patterns = OrderedDict()
        for lnum, line in self.sections['[PATTERNS]']:  # noqa: B007
            # read the lines for each pattern -- patterns can be multiple lines of arbitrary length  # noqa: E501
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            pattern_name = current[0]
            if pattern_name not in _patterns:
                _patterns[pattern_name] = []
                for i in current[1:]:
                    _patterns[pattern_name].append(float(i))
            else:
                for i in current[1:]:
                    _patterns[pattern_name].append(float(i))
        for pattern_name, pattern in _patterns.items():
            # add the patterns to the water newtork model
            self.wn.add_pattern(pattern_name, pattern)
        if not self.wn.options.hydraulic.pattern and '1' in _patterns.keys():  # noqa: SIM118
            # If there is a pattern called "1", then it is the default pattern if no other is supplied  # noqa: E501
            self.wn.options.hydraulic.pattern = '1'
        elif self.wn.options.hydraulic.pattern not in _patterns.keys():  # noqa: SIM118
            # Sanity check - if the default pattern does not exist and it is not '1' then balk  # noqa: E501
            # If default is '1' but it does not exist, then it is constant
            # Any other default that does not exist is an error
            if (
                self.wn.options.hydraulic.pattern is not None
                and self.wn.options.hydraulic.pattern != '1'
            ):
                raise KeyError(  # noqa: TRY003
                    f'Default pattern {self.wn.options.hydraulic.pattern} is undefined'  # noqa: EM102, E501
                )
            self.wn.options.hydraulic.pattern = None

    def _write_patterns(self, f, wn):  # noqa: ANN001, ANN202
        num_columns = 6
        f.write('[PATTERNS]\n'.encode(sys_default_enc))
        f.write(
            '{:10s} {:10s}\n'.format(';ID', 'Multipliers').encode(sys_default_enc)
        )
        patterns = list(wn.pattern_name_list)
        # patterns.sort()  # noqa: ERA001
        for pattern_name in patterns:
            pattern = wn.get_pattern(pattern_name)
            count = 0
            for i in pattern.multipliers:
                if count % num_columns == 0:
                    f.write(f'\n{pattern_name:s} {i:f}'.encode(sys_default_enc))
                else:
                    f.write(f' {i:f}'.encode(sys_default_enc))
                count += 1  # noqa: SIM113
            f.write('\n'.encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_energy(self):  # noqa: ANN202, C901, PLR0912
        for lnum, line in self.sections['[ENERGY]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            # Only add head curves for pumps
            if current[0].upper() == 'GLOBAL':
                if current[1].upper() == 'PRICE':
                    self.wn.options.energy.global_price = from_si(
                        self.flow_units, float(current[2]), HydParam.Energy
                    )
                elif current[1].upper() == 'PATTERN':
                    self.wn.options.energy.global_pattern = current[2]
                elif current[1].upper() in ['EFFIC', 'EFFICIENCY']:
                    self.wn.options.energy.global_efficiency = float(current[2])
                else:
                    logger.warning('Unknown entry in ENERGY section: %s', line)
            elif current[0].upper() == 'DEMAND':
                self.wn.options.energy.demand_charge = float(current[2])
            elif current[0].upper() == 'PUMP':
                pump_name = current[1]
                pump = self.wn.links[pump_name]
                if current[2].upper() == 'PRICE':
                    pump.energy_price = from_si(
                        self.flow_units, float(current[3]), HydParam.Energy
                    )
                elif current[2].upper() == 'PATTERN':
                    pump.energy_pattern = current[3]
                elif current[2].upper() in ['EFFIC', 'EFFICIENCY']:
                    curve_name = current[3]
                    curve_points = []
                    for point in self.curves[curve_name]:
                        x = to_si(self.flow_units, point[0], HydParam.Flow)
                        y = point[1]
                        curve_points.append((x, y))
                    self.wn.add_curve(curve_name, 'EFFICIENCY', curve_points)
                    curve = self.wn.get_curve(curve_name)
                    pump.efficiency = curve
                else:
                    logger.warning('Unknown entry in ENERGY section: %s', line)
            else:
                logger.warning('Unknown entry in ENERGY section: %s', line)

    def _write_energy(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[ENERGY]\n'.encode(sys_default_enc))
        if True:  # wn.energy is not None:
            if wn.options.energy.global_efficiency is not None:
                f.write(
                    f'GLOBAL EFFICIENCY      {wn.options.energy.global_efficiency:.4f}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            if wn.options.energy.global_price is not None:
                f.write(
                    'GLOBAL PRICE           {:.4f}\n'.format(
                        to_si(
                            self.flow_units,
                            wn.options.energy.global_price,
                            HydParam.Energy,
                        )
                    ).encode(sys_default_enc)
                )
            if wn.options.energy.demand_charge is not None:
                f.write(
                    f'DEMAND CHARGE          {wn.options.energy.demand_charge:.4f}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            if wn.options.energy.global_pattern is not None:
                f.write(
                    f'GLOBAL PATTERN         {wn.options.energy.global_pattern:s}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
        lnames = list(wn.pump_name_list)
        lnames.sort()
        for pump_name in lnames:
            pump = wn.links[pump_name]
            if pump.efficiency is not None:
                f.write(
                    f'PUMP {pump_name:10s} EFFIC   {pump.efficiency.name:s}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            if pump.energy_price is not None:
                f.write(
                    f'PUMP {pump_name:10s} PRICE   {to_si(self.flow_units, pump.energy_price, HydParam.Energy):.4f}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            if pump.energy_pattern is not None:
                f.write(
                    f'PUMP {pump_name:10s} PATTERN {pump.energy_pattern:s}\n'.encode(
                        sys_default_enc
                    )
                )
        f.write('\n'.encode(sys_default_enc))

    def _read_status(self):  # noqa: ANN202
        for lnum, line in self.sections['[STATUS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            #            assert(len(current) == 2), ("Error reading [STATUS] block, Check format.")  # noqa: ERA001, E501
            link = self.wn.get_link(current[0])
            if (
                current[1].upper() == 'OPEN'
                or current[1].upper() == 'CLOSED'
                or current[1].upper() == 'ACTIVE'
            ):
                new_status = LinkStatus[current[1].upper()]
                link.initial_status = new_status
                link._user_status = new_status  # noqa: SLF001
            else:
                if isinstance(link, wntrfr.network.Valve):
                    new_status = LinkStatus.Active
                    valve_type = link.valve_type
                    if valve_type in ['PRV', 'PSV', 'PBV']:
                        setting = to_si(
                            self.flow_units, float(current[1]), HydParam.Pressure
                        )
                    elif valve_type == 'FCV':
                        setting = to_si(
                            self.flow_units, float(current[1]), HydParam.Flow
                        )
                    elif valve_type == 'TCV':
                        setting = float(current[1])
                    else:
                        continue
                else:
                    new_status = LinkStatus.Open
                    setting = float(current[1])
                #                link.setting = setting  # noqa: ERA001
                link.initial_setting = setting
                link._user_status = new_status  # noqa: SLF001
                link.initial_status = new_status

    def _write_status(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[STATUS]\n'.encode(sys_default_enc))
        f.write('{:10s} {:10s}\n'.format(';ID', 'Setting').encode(sys_default_enc))

        pnames = list(wn.pump_name_list)
        for pump_name in pnames:
            pump = wn.links[pump_name]

            if pump._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            if pump.initial_status in (LinkStatus.Closed,):
                f.write(
                    f'{pump_name:10s} {LinkStatus(pump.initial_status).name:10s}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            else:
                setting = pump.initial_setting
                if isinstance(setting, float) and setting != 1.0:
                    f.write(
                        f'{pump_name:10s} {setting:10.7g}\n'.encode(sys_default_enc)
                    )

        vnames = list(wn.valve_name_list)
        # lnames.sort()  # noqa: ERA001
        for valve_name in vnames:
            valve = wn.links[valve_name]

            if valve._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            # valve_type = valve.valve_type  # noqa: ERA001

            if valve.initial_status not in (
                LinkStatus.Active,
            ):  # LinkStatus.Opened, LinkStatus.Open,
                f.write(
                    f'{valve_name:10s} {LinkStatus(valve.initial_status).name:10s}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
        #     if valve_type in ['PRV', 'PSV', 'PBV']:
        #         valve_set = from_si(self.flow_units, valve.initial_setting, HydParam.Pressure)  # noqa: ERA001, E501
        #     elif valve_type == 'FCV':  # noqa: ERA001
        #         valve_set = from_si(self.flow_units, valve.initial_setting, HydParam.Flow)  # noqa: ERA001, E501
        #     elif valve_type == 'TCV':  # noqa: ERA001
        #         valve_set = valve.initial_setting  # noqa: ERA001
        #     elif valve_type == 'GPV':  # noqa: ERA001
        #         valve_set = None  # noqa: ERA001
        #     if valve_set is not None:
        #         f.write('{:10s} {:10.7g}\n'.format(valve_name, float(valve_set)).encode(sys_default_enc))  # noqa: ERA001, E501

        f.write('\n'.encode(sys_default_enc))

    def _read_controls(self):  # noqa: ANN202
        control_count = 0
        for lnum, line in self.sections['[CONTROLS]']:  # noqa: B007
            control_count += 1
            control_name = 'control ' + str(control_count)

            control_obj = _read_control_line(
                line, self.wn, self.flow_units, control_name
            )
            if control_obj is None:
                control_count -= 1  # control was not found
                continue

            if control_name in self.wn.control_name_list:
                warnings.warn(
                    f'One or more [CONTROLS] were duplicated in "{self.wn.name}"; duplicates are ignored.',  # noqa: E501
                    stacklevel=0,
                )
                logger.warning(f'Control already exists: "{control_name}"')  # noqa: G004
            else:
                self.wn.add_control(control_name, control_obj)

    def _write_controls(self, f, wn):  # noqa: ANN001, ANN202, C901, PLR0912, PLR0915
        def get_setting(control_action, control_name):  # noqa: ANN001, ANN202
            value = control_action._value  # noqa: SLF001
            attribute = control_action._attribute.lower()  # noqa: SLF001
            if attribute == 'status':
                setting = LinkStatus(value).name
            elif attribute == 'base_speed':
                setting = str(value)
            elif attribute == 'setting' and isinstance(
                control_action._target_obj, Valve  # noqa: SLF001
            ):
                valve = control_action._target_obj  # noqa: SLF001
                valve_type = valve.valve_type
                if valve_type == 'PRV' or valve_type == 'PSV' or valve_type == 'PBV':  # noqa: PLR1714
                    setting = str(from_si(self.flow_units, value, HydParam.Pressure))
                elif valve_type == 'FCV':
                    setting = str(from_si(self.flow_units, value, HydParam.Flow))
                elif valve_type == 'TCV':
                    setting = str(value)
                elif valve_type == 'GPV':
                    setting = value
                else:
                    raise ValueError('Valve type not recognized' + str(valve_type))
            elif attribute == 'setting':
                setting = value
            else:
                setting = None
                logger.warning(
                    'Could not write control ' + str(control_name) + ' - skipping'  # noqa: G003
                )

            return setting

        f.write('[CONTROLS]\n'.encode(sys_default_enc))
        # Time controls and conditional controls only
        for text, all_control in wn.controls():
            control_action = all_control._then_actions[0]  # noqa: SLF001

            if control_action._target_obj._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            if all_control.epanet_control_type is not _ControlType.rule:
                if (
                    len(all_control._then_actions) != 1  # noqa: SLF001
                    or len(all_control._else_actions) != 0  # noqa: SLF001
                ):
                    logger.error('Too many actions on CONTROL "%s"' % text)  # noqa: G002, UP031
                    raise RuntimeError('Too many actions on CONTROL "%s"' % text)  # noqa: UP031
                if not isinstance(control_action.target()[0], Link):
                    continue
                if isinstance(
                    all_control._condition, (SimTimeCondition, TimeOfDayCondition)  # noqa: SLF001
                ):
                    entry = '{ltype} {link} {setting} AT {compare} {time:g}\n'
                    vals = {
                        'ltype': control_action._target_obj.link_type,  # noqa: SLF001
                        'link': control_action._target_obj.name,  # noqa: SLF001
                        'setting': get_setting(control_action, text),
                        'compare': 'TIME',
                        'time': all_control._condition._threshold / 3600.0,  # noqa: SLF001
                    }
                    if vals['setting'] is None:
                        continue
                    if isinstance(all_control._condition, TimeOfDayCondition):  # noqa: SLF001
                        vals['compare'] = 'CLOCKTIME'
                    f.write(entry.format(**vals).encode(sys_default_enc))
                elif (
                    all_control._condition._source_obj._is_isolated == True  # noqa: SLF001, E712
                ):  # Sina added this
                    continue
                elif isinstance(all_control._condition, (ValueCondition)):  # noqa: SLF001
                    entry = '{ltype} {link} {setting} IF {ntype} {node} {compare} {thresh}\n'  # noqa: E501
                    vals = {
                        'ltype': control_action._target_obj.link_type,  # noqa: SLF001
                        'link': control_action._target_obj.name,  # noqa: SLF001
                        'setting': get_setting(control_action, text),
                        'ntype': all_control._condition._source_obj.node_type,  # noqa: SLF001
                        'node': all_control._condition._source_obj.name,  # noqa: SLF001
                        'compare': 'above',
                        'thresh': 0.0,
                    }
                    if vals['setting'] is None:
                        continue
                    if all_control._condition._relation in [  # noqa: SLF001
                        np.less,
                        np.less_equal,
                        Comparison.le,
                        Comparison.lt,
                    ]:
                        vals['compare'] = 'below'
                    threshold = all_control._condition._threshold  # noqa: SLF001
                    if isinstance(all_control._condition._source_obj, Tank):  # noqa: SLF001
                        vals['thresh'] = from_si(
                            self.flow_units, threshold, HydParam.HydraulicHead
                        )
                    elif isinstance(all_control._condition._source_obj, Junction):  # noqa: SLF001
                        vals['thresh'] = from_si(
                            self.flow_units, threshold, HydParam.Pressure
                        )
                    else:
                        raise RuntimeError(  # noqa: TRY004
                            'Unknown control for EPANET INP files: %s'  # noqa: UP031
                            % type(all_control)
                        )
                    f.write(entry.format(**vals).encode(sys_default_enc))
                elif not isinstance(all_control, Control):
                    raise RuntimeError(
                        'Unknown control for EPANET INP files: %s'  # noqa: UP031
                        % type(all_control)
                    )
        f.write('\n'.encode(sys_default_enc))

    def _read_rules(self):  # noqa: ANN202
        rules = _EpanetRule.parse_rules_lines(
            self.sections['[RULES]'], self.flow_units, self.mass_units
        )
        for rule in rules:
            ctrl = rule.generate_control(self.wn)
            self.wn.add_control(ctrl.name, ctrl)
            logger.debug('Added %s', str(ctrl))
        # wn._en_rules = '\n'.join(self.sections['[RULES]'])  # noqa: ERA001
        # logger.warning('RULES are reapplied directly to an Epanet INP file on write; otherwise unsupported.')  # noqa: ERA001, E501

    def _write_rules(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[RULES]\n'.encode(sys_default_enc))
        for text, all_control in wn.controls():
            entry = '{}\n'
            if all_control.epanet_control_type == _ControlType.rule:
                # Sina added thsi begin
                try:
                    if all_control._then_actions[0]._target_obj._is_isolated == True:  # noqa: SLF001, E712
                        continue
                except:  # noqa: S110, E722
                    pass

                try:
                    if all_control.condition._source_obj._is_isolated == True:  # noqa: SLF001, E712
                        continue
                except:  # noqa: S110, E722
                    pass

                # Sina added thsi end

                if all_control.name == '':
                    all_control._name = text  # noqa: SLF001
                rule = _EpanetRule('blah', self.flow_units, self.mass_units)
                rule.from_if_then_else(all_control)
                f.write(entry.format(str(rule)).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_demands(self):  # noqa: ANN202
        demand_num = 0
        has_been_read = set()
        for lnum, line in self.sections['[DEMANDS]']:  # noqa: B007
            ldata = line.split(';')
            if len(ldata) > 1 and (ldata[1] != ''):  # noqa: SIM108
                category = ldata[1]
            else:
                category = None
            current = ldata[0].split()
            if current == []:
                continue
            demand_num = demand_num + 1
            node = self.wn.get_node(current[0])
            if len(current) == 2:  # noqa: SIM108, PLR2004
                pattern = None
            else:
                pattern = self.wn.get_pattern(current[2])
            if node.name not in has_been_read:
                has_been_read.add(node.name)
                while len(node.demand_timeseries_list) > 0:
                    del node.demand_timeseries_list[-1]
            # In EPANET, the [DEMANDS] section overrides demands specified in [JUNCTIONS]  # noqa: E501
            # node.demand_timeseries_list.remove_category('EN2 base')  # noqa: ERA001
            node.demand_timeseries_list.append(
                (
                    to_si(self.flow_units, float(current[1]), HydParam.Demand),
                    pattern,
                    category,
                )
            )

    def _write_demands(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[DEMANDS]\n'.encode(sys_default_enc))
        entry = '{:10s} {:10s} {:10s}{:s}\n'
        label = '{:10s} {:10s} {:10s}\n'
        f.write(label.format(';ID', 'Demand', 'Pattern').encode(sys_default_enc))
        nodes = list(wn.junction_name_list)
        # nodes.sort()  # noqa: ERA001
        for node in nodes:
            if wn.get_node(node)._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            demands = wn.get_node(node).demand_timeseries_list
            if len(demands) > 1:
                for ct, demand in enumerate(demands):  # noqa: B007
                    cat = str(demand.category)
                    # if cat == 'EN2 base':
                    #    cat = ''  # noqa: ERA001
                    if cat.lower() == 'none':  # noqa: SIM108
                        cat = ''
                    else:
                        cat = ' ;' + demand.category
                    E = {  # noqa: N806
                        'node': node,
                        'base': from_si(
                            self.flow_units, demand.base_value, HydParam.Demand
                        ),
                        'pat': '',
                        'cat': cat,
                    }
                    if demand.pattern_name in wn.pattern_name_list:
                        E['pat'] = demand.pattern_name
                    f.write(
                        entry.format(
                            E['node'], str(E['base']), E['pat'], E['cat']
                        ).encode(sys_default_enc)
                    )
        f.write('\n'.encode(sys_default_enc))

    ### Water Quality

    def _read_quality(self):  # noqa: ANN202
        for lnum, line in self.sections['[QUALITY]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            node = self.wn.get_node(current[0])
            if self.wn.options.quality.parameter == 'CHEMICAL':
                quality = to_si(
                    self.flow_units,
                    float(current[1]),
                    QualParam.Concentration,
                    mass_units=self.mass_units,
                )
            elif self.wn.options.quality.parameter == 'AGE':
                quality = to_si(
                    self.flow_units, float(current[1]), QualParam.WaterAge
                )
            else:
                quality = float(current[1])
            node.initial_quality = quality

    def _write_quality(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[QUALITY]\n'.encode(sys_default_enc))
        entry = '{:10s} {:10s}\n'
        label = '{:10s} {:10s}\n'  # noqa: F841
        nnodes = list(wn.nodes.keys())
        # nnodes.sort()  # noqa: ERA001
        for node_name in nnodes:
            node = wn.nodes[node_name]
            if node._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            if node.initial_quality:
                if wn.options.quality.parameter == 'CHEMICAL':
                    quality = from_si(
                        self.flow_units,
                        node.initial_quality,
                        QualParam.Concentration,
                        mass_units=self.mass_units,
                    )
                elif wn.options.quality.parameter == 'AGE':
                    quality = from_si(
                        self.flow_units, node.initial_quality, QualParam.WaterAge
                    )
                else:
                    quality = node.initial_quality
                f.write(
                    entry.format(node_name, str(quality)).encode(sys_default_enc)
                )
        f.write('\n'.encode(sys_default_enc))

    def _read_reactions(self):  # noqa: ANN202, C901, PLR0912
        BulkReactionCoeff = QualParam.BulkReactionCoeff  # noqa: N806
        WallReactionCoeff = QualParam.WallReactionCoeff  # noqa: N806
        if self.mass_units is None:
            self.mass_units = MassUnits.mg
        for lnum, line in self.sections['[REACTIONS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            #            assert len(current) == 3, ('INP file option in [REACTIONS] block '  # noqa: E501
            #                                       'not recognized: ' + line)
            key1 = current[0].upper()
            key2 = current[1].upper()
            val3 = float(current[2])
            if key1 == 'ORDER':
                if key2 == 'BULK':
                    self.wn.options.reaction.bulk_order = int(float(current[2]))
                elif key2 == 'WALL':
                    self.wn.options.reaction.wall_order = int(float(current[2]))
                elif key2 == 'TANK':
                    self.wn.options.reaction.tank_order = int(float(current[2]))
            elif key1 == 'GLOBAL':
                if key2 == 'BULK':
                    self.wn.options.reaction.bulk_coeff = to_si(
                        self.flow_units,
                        val3,
                        BulkReactionCoeff,
                        mass_units=self.mass_units,
                        reaction_order=self.wn.options.reaction.bulk_order,
                    )
                elif key2 == 'WALL':
                    self.wn.options.reaction.wall_coeff = to_si(
                        self.flow_units,
                        val3,
                        WallReactionCoeff,
                        mass_units=self.mass_units,
                        reaction_order=self.wn.options.reaction.wall_order,
                    )
            elif key1 == 'BULK':
                pipe = self.wn.get_link(current[1])
                pipe.bulk_coeff = to_si(
                    self.flow_units,
                    val3,
                    BulkReactionCoeff,
                    mass_units=self.mass_units,
                    reaction_order=self.wn.options.reaction.bulk_order,
                )
            elif key1 == 'WALL':
                pipe = self.wn.get_link(current[1])
                pipe.wall_coeff = to_si(
                    self.flow_units,
                    val3,
                    WallReactionCoeff,
                    mass_units=self.mass_units,
                    reaction_order=self.wn.options.reaction.wall_order,
                )
            elif key1 == 'TANK':
                tank = self.wn.get_node(current[1])
                tank.bulk_coeff = to_si(
                    self.flow_units,
                    val3,
                    BulkReactionCoeff,
                    mass_units=self.mass_units,
                    reaction_order=self.wn.options.reaction.bulk_order,
                )
            elif key1 == 'LIMITING':
                self.wn.options.reaction.limiting_potential = float(current[2])
            elif key1 == 'ROUGHNESS':
                self.wn.options.reaction.roughness_correl = float(current[2])
            else:
                raise RuntimeError('Reaction option not recognized: %s' % key1)  # noqa: UP031

    def _write_reactions(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[REACTIONS]\n'.encode(sys_default_enc))
        f.write(
            ';Type           Pipe/Tank               Coefficient\n'.encode(
                sys_default_enc
            )
        )
        entry_int = ' {:s} {:s} {:d}\n'
        entry_float = ' {:s} {:s} {:<10.4f}\n'
        for tank_name, tank in wn.nodes(Tank):
            if tank._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            if tank.bulk_coeff is not None:
                f.write(
                    entry_float.format(
                        'TANK',
                        tank_name,
                        from_si(
                            self.flow_units,
                            tank.bulk_coeff,
                            QualParam.BulkReactionCoeff,
                            mass_units=self.mass_units,
                            reaction_order=wn.options.reaction.bulk_order,
                        ),
                    ).encode(sys_default_enc)
                )
        for pipe_name, pipe in wn.links(Pipe):
            if pipe._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            if pipe.bulk_coeff is not None:
                f.write(
                    entry_float.format(
                        'BULK',
                        pipe_name,
                        from_si(
                            self.flow_units,
                            pipe.bulk_coeff,
                            QualParam.BulkReactionCoeff,
                            mass_units=self.mass_units,
                            reaction_order=wn.options.reaction.bulk_order,
                        ),
                    ).encode(sys_default_enc)
                )
            if pipe.wall_coeff is not None:
                f.write(
                    entry_float.format(
                        'WALL',
                        pipe_name,
                        from_si(
                            self.flow_units,
                            pipe.wall_coeff,
                            QualParam.WallReactionCoeff,
                            mass_units=self.mass_units,
                            reaction_order=wn.options.reaction.wall_order,
                        ),
                    ).encode(sys_default_enc)
                )
        f.write('\n'.encode(sys_default_enc))
        #        f.write('[REACTIONS]\n'.encode(sys_default_enc))  # EPANET GUI puts this line in here  # noqa: ERA001, E501
        f.write(
            entry_int.format(
                'ORDER', 'BULK', int(wn.options.reaction.bulk_order)
            ).encode(sys_default_enc)
        )
        f.write(
            entry_int.format(
                'ORDER', 'TANK', int(wn.options.reaction.tank_order)
            ).encode(sys_default_enc)
        )
        f.write(
            entry_int.format(
                'ORDER', 'WALL', int(wn.options.reaction.wall_order)
            ).encode(sys_default_enc)
        )
        f.write(
            entry_float.format(
                'GLOBAL',
                'BULK',
                from_si(
                    self.flow_units,
                    wn.options.reaction.bulk_coeff,
                    QualParam.BulkReactionCoeff,
                    mass_units=self.mass_units,
                    reaction_order=wn.options.reaction.bulk_order,
                ),
            ).encode(sys_default_enc)
        )
        f.write(
            entry_float.format(
                'GLOBAL',
                'WALL',
                from_si(
                    self.flow_units,
                    wn.options.reaction.wall_coeff,
                    QualParam.WallReactionCoeff,
                    mass_units=self.mass_units,
                    reaction_order=wn.options.reaction.wall_order,
                ),
            ).encode(sys_default_enc)
        )
        if wn.options.reaction.limiting_potential is not None:
            f.write(
                entry_float.format(
                    'LIMITING', 'POTENTIAL', wn.options.reaction.limiting_potential
                ).encode(sys_default_enc)
            )
        if wn.options.reaction.roughness_correl is not None:
            f.write(
                entry_float.format(
                    'ROUGHNESS', 'CORRELATION', wn.options.reaction.roughness_correl
                ).encode(sys_default_enc)
            )
        f.write('\n'.encode(sys_default_enc))

    def _read_sources(self):  # noqa: ANN202
        source_num = 0
        for lnum, line in self.sections['[SOURCES]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            #            assert(len(current) >= 3), ("Error reading sources. Check format.")  # noqa: ERA001, E501
            source_num = source_num + 1
            if current[0].upper() == 'MASS':
                strength = to_si(
                    self.flow_units,
                    float(current[2]),
                    QualParam.SourceMassInject,
                    self.mass_units,
                )
            else:
                strength = to_si(
                    self.flow_units,
                    float(current[2]),
                    QualParam.Concentration,
                    self.mass_units,
                )
            if len(current) == 3:  # noqa: PLR2004
                self.wn.add_source(
                    'INP' + str(source_num), current[0], current[1], strength, None
                )
            else:
                self.wn.add_source(
                    'INP' + str(source_num),
                    current[0],
                    current[1],
                    strength,
                    current[3],
                )

    def _write_sources(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[SOURCES]\n'.encode(sys_default_enc))
        entry = '{:10s} {:10s} {:10s} {:10s}\n'
        label = '{:10s} {:10s} {:10s} {:10s}\n'
        f.write(
            label.format(';Node', 'Type', 'Quality', 'Pattern').encode(
                sys_default_enc
            )
        )
        nsources = list(wn._sources.keys())  # noqa: SLF001
        # nsources.sort()  # noqa: ERA001
        for source_name in nsources:
            source = wn._sources[source_name]  # noqa: SLF001

            if source._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue

            if source.source_type.upper() == 'MASS':
                strength = from_si(
                    self.flow_units,
                    source.strength_timeseries.base_value,
                    QualParam.SourceMassInject,
                    self.mass_units,
                )
            else:  # CONC, SETPOINT, FLOWPACED
                strength = from_si(
                    self.flow_units,
                    source.strength_timeseries.base_value,
                    QualParam.Concentration,
                    self.mass_units,
                )

            E = {  # noqa: N806
                'node': source.node_name,
                'type': source.source_type,
                'quality': str(strength),
                'pat': '',
            }
            if source.strength_timeseries.pattern_name is not None:
                E['pat'] = source.strength_timeseries.pattern_name
            f.write(
                entry.format(
                    E['node'], E['type'], str(E['quality']), E['pat']
                ).encode(sys_default_enc)
            )
        f.write('\n'.encode(sys_default_enc))

    def _read_mixing(self):  # noqa: ANN202
        for lnum, line in self.sections['[MIXING]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            key = current[1].upper()
            tank_name = current[0]
            tank = self.wn.get_node(tank_name)
            if key == 'MIXED':
                tank.mixing_model = MixType.Mix1
            elif key == '2COMP' and len(current) > 2:  # noqa: PLR2004
                tank.mixing_model = MixType.Mix2
                tank.mixing_fraction = float(current[2])
            elif key == '2COMP' and len(current) < 3:  # noqa: PLR2004
                raise RuntimeError(
                    'Mixing model 2COMP requires fraction on tank %s' % tank_name  # noqa: UP031
                )
            elif key == 'FIFO':
                tank.mixing_model = MixType.FIFO
            elif key == 'LIFO':
                tank.mixing_model = MixType.LIFO

    def _write_mixing(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[MIXING]\n'.encode(sys_default_enc))
        f.write(
            '{:20s} {:5s} {}\n'.format(';Tank ID', 'Model', 'Fraction').encode(
                sys_default_enc
            )
        )
        lnames = list(wn.tank_name_list)
        # lnames.sort()  # noqa: ERA001
        for tank_name in lnames:
            tank = wn.nodes[tank_name]
            if tank._mixing_model is not None:  # noqa: SLF001
                if tank._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                    continue
                if tank._mixing_model in [MixType.Mixed, MixType.Mix1, 0]:  # noqa: SLF001
                    f.write(f' {tank_name:19s} MIXED\n'.encode(sys_default_enc))
                elif tank._mixing_model in [  # noqa: SLF001
                    MixType.TwoComp,
                    MixType.Mix2,
                    '2comp',
                    '2COMP',
                    1,
                ]:
                    f.write(
                        f' {tank_name:19s} 2COMP  {tank.mixing_fraction}\n'.encode(
                            sys_default_enc
                        )
                    )
                elif tank._mixing_model in [MixType.FIFO, 2]:  # noqa: SLF001
                    f.write(f' {tank_name:19s} FIFO\n'.encode(sys_default_enc))
                elif tank._mixing_model in [MixType.LIFO, 3]:  # noqa: SLF001
                    f.write(f' {tank_name:19s} LIFO\n'.encode(sys_default_enc))
                elif (
                    isinstance(tank._mixing_model, str)  # noqa: SLF001
                    and tank.mixing_fraction is not None
                ):
                    f.write(
                        f' {tank_name:19s} {tank._mixing_model} {tank.mixing_fraction}\n'.encode(  # noqa: SLF001, E501
                            sys_default_enc
                        )
                    )
                elif isinstance(tank._mixing_model, str):  # noqa: SLF001
                    f.write(
                        f' {tank_name:19s} {tank._mixing_model}\n'.encode(  # noqa: SLF001
                            sys_default_enc
                        )
                    )
                else:
                    logger.warning('Unknown mixing model: %s', tank._mixing_model)  # noqa: SLF001
        f.write('\n'.encode(sys_default_enc))

    ### Options and Reporting

    def _read_options(self):  # noqa: ANN202, C901, PLR0912, PLR0915
        edata = OrderedDict()
        wn = self.wn
        opts = wn.options
        for lnum, line in self.sections['[OPTIONS]']:
            edata['lnum'] = lnum
            edata['sec'] = '[OPTIONS]'
            words, comments = _split_line(line)
            if words is not None and len(words) > 0:
                if len(words) < 2:  # noqa: PLR2004
                    edata['key'] = words[0]
                    raise RuntimeError(
                        '%(lnum)-6d %(sec)13s no value provided for %(key)s' % edata
                    )
                key = words[0].upper()
                if key == 'UNITS':
                    self.flow_units = FlowUnits[words[1].upper()]
                    opts.hydraulic.inpfile_units = words[1].upper()
                elif key == 'HEADLOSS':
                    opts.hydraulic.headloss = words[1].upper()
                elif key == 'HYDRAULICS':
                    opts.hydraulic.hydraulics = words[1].upper()
                    opts.hydraulic.hydraulics_filename = words[2]
                elif key == 'QUALITY':
                    mode = words[1].upper()
                    if mode in ['NONE', 'AGE']:
                        opts.quality.parameter = words[1].upper()
                    elif mode in ['TRACE']:
                        opts.quality.parameter = 'TRACE'
                        opts.quality.trace_node = words[2]
                    else:
                        opts.quality.parameter = 'CHEMICAL'
                        opts.quality.chemical_name = words[1]
                        if len(words) > 2:  # noqa: PLR2004
                            if 'mg' in words[2].lower():
                                self.mass_units = MassUnits.mg
                                opts.quality.inpfile_units = words[2]
                            elif 'ug' in words[2].lower():
                                self.mass_units = MassUnits.ug
                                opts.quality.inpfile_units = words[2]
                            else:
                                raise ValueError(  # noqa: TRY003
                                    'Invalid chemical units in OPTIONS section'  # noqa: EM101
                                )
                        else:
                            self.mass_units = MassUnits.mg
                            opts.quality.inpfile_units = 'mg/L'
                elif key == 'VISCOSITY':
                    opts.hydraulic.viscosity = float(words[1])
                elif key == 'DIFFUSIVITY':
                    opts.quality.diffusivity = float(words[1])
                elif key == 'SPECIFIC':
                    opts.hydraulic.specific_gravity = float(words[2])
                elif key == 'TRIALS':
                    opts.hydraulic.trials = int(float(words[1]))
                elif key == 'ACCURACY':
                    opts.hydraulic.accuracy = float(words[1])
                elif key == 'HEADERROR':
                    opts.hydraulic.headerror = float(words[1])
                elif key == 'FLOWCHANGE':
                    opts.hydraulic.flowchange = float(words[1])
                elif key == 'UNBALANCED':
                    opts.hydraulic.unbalanced = words[1].upper()
                    if len(words) > 2:  # noqa: PLR2004
                        opts.hydraulic.unbalanced_value = int(words[2])
                elif key == 'MINIMUM':
                    minimum_pressure = to_si(
                        self.flow_units, float(words[2]), HydParam.Pressure
                    )
                    opts.hydraulic.minimum_pressure = minimum_pressure
                elif key == 'REQUIRED':
                    required_pressure = to_si(
                        self.flow_units, float(words[2]), HydParam.Pressure
                    )
                    opts.hydraulic.required_pressure = required_pressure
                elif key == 'PRESSURE':
                    if len(words) > 2:  # noqa: PLR2004
                        if words[1].upper() == 'EXPONENT':
                            opts.hydraulic.pressure_exponent = float(words[2])
                        else:
                            edata['key'] = ' '.join(words)
                            raise RuntimeError(
                                '%(lnum)-6d %(sec)13s unknown option %(key)s' % edata
                            )
                    else:
                        opts.hydraulic.inpfile_pressure_units = words[1]
                elif key == 'PATTERN':
                    opts.hydraulic.pattern = words[1]
                elif key == 'DEMAND':
                    if len(words) > 2:  # noqa: PLR2004
                        if words[1].upper() == 'MULTIPLIER':
                            opts.hydraulic.demand_multiplier = float(words[2])
                        elif words[1].upper() == 'MODEL':
                            opts.hydraulic.demand_model = words[2]
                        else:
                            edata['key'] = ' '.join(words)
                            raise RuntimeError(
                                '%(lnum)-6d %(sec)13s unknown option %(key)s' % edata
                            )
                    else:
                        edata['key'] = ' '.join(words)
                        raise RuntimeError(
                            '%(lnum)-6d %(sec)13s no value provided for %(key)s'
                            % edata
                        )
                elif key == 'EMITTER':
                    if len(words) > 2:  # noqa: PLR2004
                        opts.hydraulic.emitter_exponent = float(words[2])
                    else:
                        edata['key'] = 'EMITTER EXPONENT'
                        raise RuntimeError(
                            '%(lnum)-6d %(sec)13s no value provided for %(key)s'
                            % edata
                        )
                elif key == 'TOLERANCE':
                    opts.quality.tolerance = float(words[1])
                elif key == 'CHECKFREQ':
                    opts.hydraulic.checkfreq = float(words[1])
                elif key == 'MAXCHECK':
                    opts.hydraulic.maxcheck = float(words[1])
                elif key == 'DAMPLIMIT':
                    opts.hydraulic.damplimit = float(words[1])
                elif key == 'MAP':
                    opts.graphics.map_filename = words[1]
                elif len(words) == 2:  # noqa: PLR2004
                    edata['key'] = words[0]
                    setattr(opts, words[0].lower(), float(words[1]))
                    logger.warning(
                        '%(lnum)-6d %(sec)13s option "%(key)s" is undocumented; adding, but please verify syntax',  # noqa: E501
                        edata,
                    )
                elif len(words) == 3:  # noqa: PLR2004
                    edata['key'] = words[0] + ' ' + words[1]
                    setattr(
                        opts,
                        words[0].lower() + '_' + words[1].lower(),
                        float(words[2]),
                    )
                    logger.warning(
                        '%(lnum)-6d %(sec)13s option "%(key)s" is undocumented; adding, but please verify syntax',  # noqa: E501
                        edata,
                    )
        if isinstance(opts.time.report_timestep, (float, int)):
            if opts.time.report_timestep < opts.time.hydraulic_timestep:
                raise RuntimeError(  # noqa: TRY003
                    'opts.report_timestep must be greater than or equal to opts.hydraulic_timestep.'  # noqa: EM101, E501
                )
            if opts.time.report_timestep % opts.time.hydraulic_timestep != 0:
                raise RuntimeError(  # noqa: TRY003
                    'opts.report_timestep must be a multiple of opts.hydraulic_timestep'  # noqa: EM101, E501
                )

    def _write_options(self, f, wn, version=2.2):  # noqa: ANN001, ANN202, C901, PLR0912, PLR0915
        f.write('[OPTIONS]\n'.encode(sys_default_enc))
        entry_string = '{:20s} {:20s}\n'
        entry_float = '{:20s} {:.11g}\n'
        f.write(
            entry_string.format('UNITS', self.flow_units.name).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_string.format('HEADLOSS', wn.options.hydraulic.headloss).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format(
                'SPECIFIC GRAVITY', wn.options.hydraulic.specific_gravity
            ).encode(sys_default_enc)
        )

        f.write(
            entry_float.format('VISCOSITY', wn.options.hydraulic.viscosity).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format('TRIALS', wn.options.hydraulic.trials).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format('ACCURACY', wn.options.hydraulic.accuracy).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format('CHECKFREQ', wn.options.hydraulic.checkfreq).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format('MAXCHECK', wn.options.hydraulic.maxcheck).encode(
                sys_default_enc
            )
        )

        # EPANET 2.2 OPTIONS
        if version == 2.0:  # noqa: PLR2004
            pass
        else:
            if wn.options.hydraulic.headerror != 0:
                f.write(
                    entry_float.format(
                        'HEADERROR', wn.options.hydraulic.headerror
                    ).encode(sys_default_enc)
                )

            if wn.options.hydraulic.flowchange != 0:
                f.write(
                    entry_float.format(
                        'FLOWCHANGE', wn.options.hydraulic.flowchange
                    ).encode(sys_default_enc)
                )

        # EPANET 2.x OPTIONS
        if wn.options.hydraulic.damplimit != 0:
            f.write(
                entry_float.format(
                    'DAMPLIMIT', wn.options.hydraulic.damplimit
                ).encode(sys_default_enc)
            )

        if wn.options.hydraulic.unbalanced_value is None:
            f.write(
                entry_string.format(
                    'UNBALANCED', wn.options.hydraulic.unbalanced
                ).encode(sys_default_enc)
            )
        else:
            f.write(
                '{:20s} {:s} {:d}\n'.format(
                    'UNBALANCED',
                    wn.options.hydraulic.unbalanced,
                    wn.options.hydraulic.unbalanced_value,
                ).encode(sys_default_enc)
            )

        if wn.options.hydraulic.pattern is not None:
            f.write(
                entry_string.format('PATTERN', wn.options.hydraulic.pattern).encode(
                    sys_default_enc
                )
            )

        f.write(
            entry_float.format(
                'DEMAND MULTIPLIER', wn.options.hydraulic.demand_multiplier
            ).encode(sys_default_enc)
        )

        # EPANET 2.2 OPTIONS
        if version == 2.0:  # noqa: PLR2004
            if wn.options.hydraulic.demand_model in ['PDA', 'PDD']:
                logger.critical(
                    'You have specified a PDD analysis using EPANET 2.0. This is not supported in EPANET 2.0. The analysis will default to DD mode.'  # noqa: E501
                )
        elif wn.options.hydraulic.demand_model in ['PDA', 'PDD']:
            f.write(
                '{:20s} {}\n'.format(
                    'DEMAND MODEL', wn.options.hydraulic.demand_model
                ).encode(sys_default_enc)
            )

            minimum_pressure = from_si(
                self.flow_units,
                wn.options.hydraulic.minimum_pressure,
                HydParam.Pressure,
            )
            f.write(
                '{:20s} {:.2f}\n'.format(
                    'MINIMUM PRESSURE', minimum_pressure
                ).encode(sys_default_enc)
            )

            required_pressure = from_si(
                self.flow_units,
                wn.options.hydraulic.required_pressure,
                HydParam.Pressure,
            )
            if (
                required_pressure >= 0.1  # noqa: PLR2004
            ):  # EPANET lower limit on required pressure = 0.1 (in psi or m)
                f.write(
                    '{:20s} {:.2f}\n'.format(
                        'REQUIRED PRESSURE', required_pressure
                    ).encode(sys_default_enc)
                )
            else:
                warnings.warn(  # noqa: B028
                    'REQUIRED PRESSURE is below the lower limit for EPANET (0.1 in psi or m). The value has been set to 0.1 in the INP file.'  # noqa: E501
                )
                logger.warning(
                    'REQUIRED PRESSURE is below the lower limit for EPANET (0.1 in psi or m). The value has been set to 0.1 in the INP file.'  # noqa: E501
                )
                f.write(
                    '{:20s} {:.2f}\n'.format('REQUIRED PRESSURE', 0.1).encode(
                        sys_default_enc
                    )
                )
            f.write(
                '{:20s} {}\n'.format(
                    'PRESSURE EXPONENT', wn.options.hydraulic.pressure_exponent
                ).encode(sys_default_enc)
            )

        if wn.options.hydraulic.inpfile_pressure_units is not None:
            f.write(
                entry_string.format(
                    'PRESSURE', wn.options.hydraulic.inpfile_pressure_units
                ).encode(sys_default_enc)
            )

        # EPANET 2.0+ OPTIONS
        f.write(
            entry_float.format(
                'EMITTER EXPONENT', wn.options.hydraulic.emitter_exponent
            ).encode(sys_default_enc)
        )

        if wn.options.quality.parameter.upper() in ['NONE', 'AGE']:
            f.write(
                entry_string.format('QUALITY', wn.options.quality.parameter).encode(
                    sys_default_enc
                )
            )
        elif wn.options.quality.parameter.upper() in ['TRACE']:
            f.write(
                '{:20s} {} {}\n'.format(
                    'QUALITY',
                    wn.options.quality.parameter,
                    wn.options.quality.trace_node,
                ).encode(sys_default_enc)
            )
        else:
            f.write(
                '{:20s} {} {}\n'.format(
                    'QUALITY',
                    wn.options.quality.chemical_name,
                    wn.options.quality.inpfile_units,
                ).encode(sys_default_enc)
            )

        f.write(
            entry_float.format('DIFFUSIVITY', wn.options.quality.diffusivity).encode(
                sys_default_enc
            )
        )

        f.write(
            entry_float.format('TOLERANCE', wn.options.quality.tolerance).encode(
                sys_default_enc
            )
        )

        if wn.options.hydraulic.hydraulics is not None:
            f.write(
                '{:20s} {:s} {:<30s}\n'.format(
                    'HYDRAULICS',
                    wn.options.hydraulic.hydraulics,
                    wn.options.hydraulic.hydraulics_filename,
                ).encode(sys_default_enc)
            )

        if wn.options.graphics.map_filename is not None:
            f.write(
                entry_string.format('MAP', wn.options.graphics.map_filename).encode(
                    sys_default_enc
                )
            )
        f.write('\n'.encode(sys_default_enc))

    def _read_times(self):  # noqa: ANN202
        opts = self.wn.options
        time_format = ['am', 'AM', 'pm', 'PM']
        for lnum, line in self.sections['[TIMES]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if current[0].upper() == 'DURATION':
                opts.time.duration = (
                    int(float(current[1]) * 3600)
                    if _is_number(current[1])
                    else int(_str_time_to_sec(current[1]))
                )
            elif current[0].upper() == 'HYDRAULIC':
                opts.time.hydraulic_timestep = (
                    int(float(current[2]) * 3600)
                    if _is_number(current[2])
                    else int(_str_time_to_sec(current[2]))
                )
            elif current[0].upper() == 'QUALITY':
                opts.time.quality_timestep = (
                    int(float(current[2]) * 3600)
                    if _is_number(current[2])
                    else int(_str_time_to_sec(current[2]))
                )
            elif current[1].upper() == 'CLOCKTIME':
                if len(current) > 3:  # noqa: SIM108, PLR2004
                    time_format = current[3].upper()
                else:
                    # Kludge for 24hr time that needs an AM/PM
                    time_format = 'AM'
                time = current[2]
                opts.time.start_clocktime = _clock_time_to_sec(time, time_format)
            elif current[0].upper() == 'STATISTIC':
                opts.time.statistic = current[1].upper()
            else:
                # Other time options: RULE TIMESTEP, PATTERN TIMESTEP, REPORT TIMESTEP, REPORT START  # noqa: E501
                key_string = current[0] + '_' + current[1]
                setattr(
                    opts.time,
                    key_string.lower(),
                    int(float(current[2]) * 3600)
                    if _is_number(current[2])
                    else int(_str_time_to_sec(current[2])),
                )

    def _write_times(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[TIMES]\n'.encode(sys_default_enc))
        entry = '{:20s} {:10s}\n'
        time_entry = '{:20s} {:02d}:{:02d}:{:02d}\n'
        time = wn.options.time

        hrs, mm, sec = _sec_to_string(time.duration)
        f.write(time_entry.format('DURATION', hrs, mm, sec).encode(sys_default_enc))

        hrs, mm, sec = _sec_to_string(time.hydraulic_timestep)
        f.write(
            time_entry.format('HYDRAULIC TIMESTEP', hrs, mm, sec).encode(
                sys_default_enc
            )
        )

        hrs, mm, sec = _sec_to_string(time.quality_timestep)
        f.write(
            time_entry.format('QUALITY TIMESTEP', hrs, mm, sec).encode(
                sys_default_enc
            )
        )

        hrs, mm, sec = _sec_to_string(time.pattern_timestep)
        f.write(
            time_entry.format('PATTERN TIMESTEP', hrs, mm, sec).encode(
                sys_default_enc
            )
        )

        hrs, mm, sec = _sec_to_string(time.pattern_start)
        f.write(
            time_entry.format('PATTERN START', hrs, mm, sec).encode(sys_default_enc)
        )

        hrs, mm, sec = _sec_to_string(time.report_timestep)
        f.write(
            time_entry.format('REPORT TIMESTEP', hrs, mm, sec).encode(
                sys_default_enc
            )
        )

        hrs, mm, sec = _sec_to_string(time.report_start)
        f.write(
            time_entry.format('REPORT START', hrs, mm, sec).encode(sys_default_enc)
        )

        hrs, mm, sec = _sec_to_string(time.start_clocktime)

        # Sina added this to WNTR-1: thsi adds the abikity to run corerctly for
        # time steps that are more than the first day
        day = int(hrs / 24)
        hrs -= day * 24

        if hrs < 12:  # noqa: PLR2004
            time_format = ' AM'
        else:
            hrs -= 12
            time_format = ' PM'
        f.write(
            '{:20s} {:02d}:{:02d}:{:02d}{:s}\n'.format(
                'START CLOCKTIME', hrs, mm, sec, time_format
            ).encode(sys_default_enc)
        )

        hrs, mm, sec = _sec_to_string(time.rule_timestep)

        f.write(
            time_entry.format('RULE TIMESTEP', hrs, mm, int(sec)).encode(
                sys_default_enc
            )
        )
        f.write(
            entry.format('STATISTIC', wn.options.time.statistic).encode(
                sys_default_enc
            )
        )
        f.write('\n'.encode(sys_default_enc))

    def _read_report(self):  # noqa: ANN202, C901, PLR0912
        for lnum, line in self.sections['[REPORT]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if current[0].upper() in ['PAGE', 'PAGESIZE']:
                self.wn.options.report.pagesize = int(current[1])
            elif current[0].upper() in ['FILE']:
                self.wn.options.report.file = current[1]
            elif current[0].upper() in ['STATUS']:
                self.wn.options.report.status = current[1].upper()
            elif current[0].upper() in ['SUMMARY']:
                self.wn.options.report.summary = current[1].upper()
            elif current[0].upper() in ['ENERGY']:
                self.wn.options.report.energy = current[1].upper()
            elif current[0].upper() in ['NODES']:
                if current[1].upper() in ['NONE']:
                    self.wn.options.report.nodes = False
                elif current[1].upper() in ['ALL']:
                    self.wn.options.report.nodes = True
                elif not isinstance(self.wn.options.report.nodes, list):
                    self.wn.options.report.nodes = []
                    for ct in range(len(current) - 2):
                        i = ct + 2
                        self.wn.options.report.nodes.append(current[i])
                else:
                    for ct in range(len(current) - 2):
                        i = ct + 2
                        self.wn.options.report.nodes.append(current[i])
            elif current[0].upper() in ['LINKS']:
                if current[1].upper() in ['NONE']:
                    self.wn.options.report.links = False
                elif current[1].upper() in ['ALL']:
                    self.wn.options.report.links = True
                elif not isinstance(self.wn.options.report.links, list):
                    self.wn.options.report.links = []
                    for ct in range(len(current) - 2):
                        i = ct + 2
                        self.wn.options.report.links.append(current[i])
                else:
                    for ct in range(len(current) - 2):
                        i = ct + 2
                        self.wn.options.report.links.append(current[i])
            elif (
                current[0].lower() not in self.wn.options.report.report_params.keys()  # noqa: SIM118
            ):
                logger.warning('Unknown report parameter: %s', current[0])
                continue
            elif current[1].upper() in ['YES']:
                self.wn.options.report.report_params[current[0].lower()] = True
            elif current[1].upper() in ['NO']:
                self.wn.options.report.report_params[current[0].lower()] = False
            else:
                self.wn.options.report.param_opts[current[0].lower()][
                    current[1].upper()
                ] = float(current[2])

    def _write_report(self, f, wn):  # noqa: ANN001, ANN202, C901, PLR0912
        f.write('[REPORT]\n'.encode(sys_default_enc))
        report = wn.options.report
        if report.status.upper() != 'NO':
            f.write(f'STATUS     {report.status}\n'.encode(sys_default_enc))
        if report.summary.upper() != 'YES':
            f.write(f'SUMMARY    {report.summary}\n'.encode(sys_default_enc))
        if report.pagesize is not None:
            f.write(f'PAGE       {report.pagesize}\n'.encode(sys_default_enc))
        if report.report_filename is not None:
            f.write(f'FILE       {report.report_filename}\n'.encode(sys_default_enc))
        if report.energy.upper() != 'NO':
            f.write(f'ENERGY     {report.status}\n'.encode(sys_default_enc))
        if report.nodes is True:
            f.write('NODES      ALL\n'.encode(sys_default_enc))
        elif isinstance(report.nodes, str):
            f.write(f'NODES      {report.nodes}\n'.encode(sys_default_enc))
        elif isinstance(report.nodes, list):
            for ct, node in enumerate(report.nodes):
                if ct == 0:
                    f.write(f'NODES      {node}'.encode(sys_default_enc))
                elif ct % 10 == 0:
                    f.write(f'\nNODES      {node}'.encode(sys_default_enc))
                else:
                    f.write(f' {node}'.encode(sys_default_enc))
            f.write('\n'.encode(sys_default_enc))
        if report.links is True:
            f.write('LINKS      ALL\n'.encode(sys_default_enc))
        elif isinstance(report.links, str):
            f.write(f'LINKS      {report.links}\n'.encode(sys_default_enc))
        elif isinstance(report.links, list):
            for ct, link in enumerate(report.links):
                if ct == 0:
                    f.write(f'LINKS      {link}'.encode(sys_default_enc))
                elif ct % 10 == 0:
                    f.write(f'\nLINKS      {link}'.encode(sys_default_enc))
                else:
                    f.write(f' {link}'.encode(sys_default_enc))
            f.write('\n'.encode(sys_default_enc))
        # FIXME: defaults no longer located here  # noqa: FIX001, TD001, TD002, TD003
        #        for key, item in report.report_params.items():
        #            if item[1] != item[0]:
        #                f.write('{:10s} {}\n'.format(key.upper(), item[1]).encode(sys_default_enc))  # noqa: ERA001, E501
        for key, item in report.param_opts.items():
            for opt, val in item.items():
                f.write(
                    f'{key.upper():10s} {opt.upper():10s} {val}\n'.encode(
                        sys_default_enc
                    )
                )
        f.write('\n'.encode(sys_default_enc))

    ### Network Map/Tags

    def _read_coordinates(self):  # noqa: ANN202
        for lnum, line in self.sections['[COORDINATES]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            #            assert(len(current) == 3), ("Error reading node coordinates. Check format.")  # noqa: ERA001, E501
            node = self.wn.get_node(current[0])
            node.coordinates = (float(current[1]), float(current[2]))

    def _write_coordinates(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[COORDINATES]\n'.encode(sys_default_enc))
        entry = '{:10s} {:20.9f} {:20.9f}\n'
        label = '{:10s} {:10s} {:10s}\n'
        f.write(label.format(';Node', 'X-Coord', 'Y-Coord').encode(sys_default_enc))
        for name, node in wn.nodes():
            if node._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            val = node.coordinates
            f.write(entry.format(name, val[0], val[1]).encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_vertices(self):  # noqa: ANN202
        for lnum, line in self.sections['[VERTICES]']:  # noqa: B007
            line = line.split(';')[0].strip()  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if len(current) != 3:  # noqa: PLR2004
                logger.warning('Invalid VERTICES line: %s', line)
                continue
            link_name = current[0]
            link = self.wn.get_link(link_name)
            link._vertices.append((float(current[1]), float(current[2])))  # noqa: SLF001

    def _write_vertices(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[VERTICES]\n'.encode(sys_default_enc))
        entry = '{:10s} {:20.9f} {:20.9f}\n'
        label = '{:10s} {:10s} {:10s}\n'
        f.write(label.format(';Link', 'X-Coord', 'Y-Coord').encode(sys_default_enc))
        for name, link in wn.links():
            if link._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            for vert in (
                link._vertices  # noqa: SLF001
            ):  # Sina: I unindented this and the next line. Possible Bug in WNTR-1
                f.write(entry.format(name, vert[0], vert[1]).encode(sys_default_enc))

        f.write('\n'.encode(sys_default_enc))

    def _read_labels(self):  # noqa: ANN202
        labels = []
        for lnum, line in self.sections['[LABELS]']:  # noqa: B007
            line = line.split(';')[0].strip()  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            labels.append(line)
        self.wn._labels = labels  # noqa: SLF001

    def _write_labels(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[LABELS]\n'.encode(sys_default_enc))
        if wn._labels is not None:  # noqa: SLF001
            for label in wn._labels:  # noqa: SLF001
                f.write(f' {label}\n'.encode(sys_default_enc))
        f.write('\n'.encode(sys_default_enc))

    def _read_backdrop(self):  # noqa: ANN202
        for lnum, line in self.sections['[BACKDROP]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            key = current[0].upper()
            if key == 'DIMENSIONS' and len(current) > 4:  # noqa: PLR2004
                self.wn.options.graphics.dimensions = [
                    current[1],
                    current[2],
                    current[3],
                    current[4],
                ]
            elif key == 'UNITS' and len(current) > 1:
                self.wn.options.graphics.units = current[1]
            elif key == 'FILE' and len(current) > 1:
                self.wn.options.graphics.image_filename = current[1]
            elif key == 'OFFSET' and len(current) > 2:  # noqa: PLR2004
                self.wn.options.graphics.offset = [current[1], current[2]]

    def _write_backdrop(self, f, wn):  # noqa: ANN001, ANN202
        if wn.options.graphics is not None:
            f.write('[BACKDROP]\n'.encode(sys_default_enc))
            if wn.options.graphics.dimensions is not None:
                f.write(
                    f'DIMENSIONS    {wn.options.graphics.dimensions[0]}    {wn.options.graphics.dimensions[1]}    {wn.options.graphics.dimensions[2]}    {wn.options.graphics.dimensions[3]}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            if wn.options.graphics.units is not None:
                f.write(
                    f'UNITS    {wn.options.graphics.units}\n'.encode(sys_default_enc)
                )
            if wn.options.graphics.image_filename is not None:
                f.write(
                    f'FILE    {wn.options.graphics.image_filename}\n'.encode(
                        sys_default_enc
                    )
                )
            if wn.options.graphics.offset is not None:
                f.write(
                    f'OFFSET    {wn.options.graphics.offset[0]}    {wn.options.graphics.offset[1]}\n'.encode(  # noqa: E501
                        sys_default_enc
                    )
                )
            f.write('\n'.encode(sys_default_enc))

    def _read_tags(self):  # noqa: ANN202
        for lnum, line in self.sections['[TAGS]']:  # noqa: B007
            line = line.split(';')[0]  # noqa: PLW2901
            current = line.split()
            if current == []:
                continue
            if current[0] == 'NODE':
                node = self.wn.get_node(current[1])
                node.tag = current[2]
            elif current[0] == 'LINK':
                link = self.wn.get_link(current[1])
                link.tag = current[2]
            else:
                continue

    def _write_tags(self, f, wn):  # noqa: ANN001, ANN202
        f.write('[TAGS]\n'.encode(sys_default_enc))
        entry = '{:10s} {:10s} {:10s}\n'
        label = '{:10s} {:10s} {:10s}\n'
        f.write(label.format(';type', 'name', 'tag').encode(sys_default_enc))
        nnodes = list(wn.node_name_list)
        # nnodes.sort()  # noqa: ERA001
        for node_name in nnodes:
            node = wn.nodes[node_name]
            if node._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            if node.tag:
                f.write(
                    entry.format('NODE', node_name, node.tag).encode(sys_default_enc)
                )
        nlinks = list(wn.link_name_list)
        nlinks.sort()
        for link_name in nlinks:
            link = wn.links[link_name]

            if link._is_isolated == True:  # Sina added this  # noqa: SLF001, E712
                continue
            if link.tag:
                f.write(
                    entry.format('LINK', link_name, link.tag).encode(sys_default_enc)
                )
        f.write('\n'.encode(sys_default_enc))

    ### End of File

    def _read_end(self):  # noqa: ANN202
        """Finalize read by verifying that all curves have been dealt with"""  # noqa: D400, D415

        def create_curve(curve_name):  # noqa: ANN001, ANN202
            curve_points = []
            if (
                curve_name not in self.wn.curve_name_list
                or self.wn.get_curve(curve_name) is None
            ):
                for point in self.curves[curve_name]:
                    x = point[0]
                    y = point[1]
                    curve_points.append((x, y))
                self.wn.add_curve(curve_name, None, curve_points)
            curve = self.wn.get_curve(curve_name)
            return curve  # noqa: RET504

        curve_name_list = self.wn.curve_name_list
        for name, curvedata in self.curves.items():  # noqa: B007, PERF102
            if name not in curve_name_list or self.wn.get_curve(name) is None:
                warnings.warn(  # noqa: B028
                    f'Not all curves were used in "{self.wn.name}"; added with type None, units conversion left to user'  # noqa: E501
                )
                logger.warning(
                    f'Curve was not used: "{name}"; saved as curve type None and unit conversion not performed'  # noqa: G004, E501
                )
                create_curve(name)

    def _write_end(self, f, wn):  # noqa: ANN001, ANN202, ARG002
        f.write('[END]\n'.encode(sys_default_enc))


class _EpanetRule:
    """contains the text for an EPANET rule"""  # noqa: D400, D415

    def __init__(self, ruleID, inp_units=None, mass_units=None):  # noqa: ANN001, ANN204, N803
        self.inp_units = inp_units
        self.mass_units = mass_units
        self.ruleID = ruleID
        self._if_clauses = []
        self._then_clauses = []
        self._else_clauses = []
        self.priority = 0

    @classmethod
    def parse_rules_lines(  # noqa: C901, PLR0912, PLR0915
        cls, lines, flow_units=FlowUnits.SI, mass_units=MassUnits.mg  # noqa: ANN001
    ) -> list:
        rules = list()  # noqa: C408
        rule = None
        in_if = False
        in_then = False
        in_else = False
        new_lines = list()  # noqa: C408
        new_line = list()  # noqa: C408
        for line in lines:
            if isinstance(line, (tuple, list)):
                line = line[1]  # noqa: PLW2901
            line = line.split(';')[0]  # noqa: PLW2901
            words = line.strip().split()
            for word in words:
                if word.upper() in [  # noqa: SIM102
                    'RULE',
                    'IF',
                    'THEN',
                    'ELSE',
                    'AND',
                    'OR',
                    'PRIORITY',
                ]:
                    if len(new_line) > 0:
                        text = ' '.join(new_line)
                        new_lines.append(text)
                        new_line = list()  # noqa: C408
                new_line.append(word)
        if len(new_line) > 0:
            text = ' '.join(new_line)
            new_lines.append(text)

        for line in new_lines:
            words = line.split()
            if words == []:
                continue
            if len(words) == 0:
                continue
            if words[0].upper() == 'RULE':
                if rule is not None:
                    rules.append(rule)
                rule = _EpanetRule(words[1], flow_units, mass_units)
                in_if = False
                in_then = False
                in_else = False
            elif words[0].upper() == 'IF':
                in_if = True
                in_then = False
                in_else = False
                rule.add_if(line)
            elif words[0].upper() == 'THEN':
                in_if = False
                in_then = True
                in_else = False
                rule.add_then(line)
            elif words[0].upper() == 'ELSE':
                in_if = False
                in_then = False
                in_else = True
                rule.add_else(line)
            elif words[0].upper() == 'PRIORITY':
                in_if = False
                in_then = False
                in_else = False
                rule.set_priority(words[1])
            elif in_if:
                rule.add_if(line)
            elif in_then:
                rule.add_then(line)
            elif in_else:
                rule.add_else(line)
            else:
                continue
        if rule is not None:
            rules.append(rule)
        return rules

    def from_if_then_else(self, control):  # noqa: ANN001, ANN202
        """Create a rule from a Rule object"""  # noqa: D400, D415
        if isinstance(control, Rule):
            self.ruleID = control.name
            self.add_control_condition(control._condition)  # noqa: SLF001
            for ct, action in enumerate(control._then_actions):  # noqa: SLF001
                if ct == 0:
                    self.add_action_on_true(action)
                else:
                    self.add_action_on_true(action, '  AND')
            for ct, action in enumerate(control._else_actions):  # noqa: SLF001
                if ct == 0:
                    self.add_action_on_false(action)
                else:
                    self.add_action_on_false(action, '  AND')
            self.set_priority(control._priority)  # noqa: SLF001
        else:
            raise ValueError(  # noqa: TRY004
                'Invalid control type for rules: %s' % control.__class__.__name__  # noqa: UP031
            )

    def add_if(self, clause):  # noqa: ANN001, ANN202
        """Add an "if/and/or" clause from an INP file"""  # noqa: D400, D415
        self._if_clauses.append(clause)

    def add_control_condition(self, condition, prefix=' IF'):  # noqa: ANN001, ANN202, C901, PLR0912
        """Add a ControlCondition from an IfThenElseControl"""  # noqa: D400, D415
        if isinstance(condition, OrCondition):
            self.add_control_condition(condition._condition_1, prefix)  # noqa: SLF001
            self.add_control_condition(condition._condition_2, '  OR')  # noqa: SLF001
        elif isinstance(condition, AndCondition):
            self.add_control_condition(condition._condition_1, prefix)  # noqa: SLF001
            self.add_control_condition(condition._condition_2, '  AND')  # noqa: SLF001
        elif isinstance(condition, TimeOfDayCondition):
            fmt = '{} SYSTEM CLOCKTIME {} {}'
            clause = fmt.format(
                prefix,
                condition._relation.text,  # noqa: SLF001
                condition._sec_to_clock(condition._threshold),  # noqa: SLF001
            )
            self.add_if(clause)
        elif isinstance(condition, SimTimeCondition):
            fmt = '{} SYSTEM TIME {} {}'
            clause = fmt.format(
                prefix,
                condition._relation.text,  # noqa: SLF001
                condition._sec_to_hours_min_sec(condition._threshold),  # noqa: SLF001
            )
            self.add_if(clause)
        elif isinstance(condition, ValueCondition):
            fmt = (
                '{} {} {} {} {} {}'  # CONJ, TYPE, ID, ATTRIBUTE, RELATION, THRESHOLD
            )
            attr = condition._source_attr  # noqa: SLF001
            val_si = condition._repr_value(attr, condition._threshold)  # noqa: SLF001
            if attr.lower() in ['demand']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Demand):.6g}'
            elif attr.lower() in ['head', 'level']:
                value = (
                    f'{from_si(self.inp_units, val_si, HydParam.HydraulicHead):.6g}'
                )
            elif attr.lower() in ['flow']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Flow):.6g}'
            elif attr.lower() in ['pressure']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Pressure):.6g}'
            elif attr.lower() in ['setting']:
                if isinstance(condition._source_obj, Valve):  # noqa: SLF001
                    if condition._source_obj.valve_type.upper() in [  # noqa: SLF001
                        'PRV',
                        'PBV',
                        'PSV',
                    ]:
                        value = from_si(self.inp_units, val_si, HydParam.Pressure)
                    elif condition._source_obj.valve_type.upper() in ['FCV']:  # noqa: SLF001
                        value = from_si(self.inp_units, val_si, HydParam.Flow)
                    else:
                        value = val_si
                else:
                    value = val_si
                value = f'{value:.6g}'
            else:  # status
                value = val_si
            if isinstance(condition._source_obj, Valve):  # noqa: SLF001
                cls = 'Valve'
            elif isinstance(condition._source_obj, Pump):  # noqa: SLF001
                cls = 'Pump'
            else:
                cls = condition._source_obj.__class__.__name__  # noqa: SLF001
            clause = fmt.format(
                prefix,
                cls,
                condition._source_obj.name,  # noqa: SLF001
                condition._source_attr,  # noqa: SLF001
                condition._relation.symbol,  # noqa: SLF001
                value,
            )
            self.add_if(clause)
        else:
            raise ValueError('Unknown ControlCondition for EPANET Rules')  # noqa: EM101, TRY003, TRY004

    def add_then(self, clause):  # noqa: ANN001, ANN202
        """Add a "then/and" clause from an INP file"""  # noqa: D400, D415
        self._then_clauses.append(clause)

    def add_action_on_true(self, action, prefix=' THEN'):  # noqa: ANN001, ANN202, C901, PLR0912
        """Add a "then" action from an IfThenElseControl"""  # noqa: D400, D415
        if isinstance(action, ControlAction):
            fmt = '{} {} {} {} = {}'
            attr = action._attribute  # noqa: SLF001
            val_si = action._repr_value()  # noqa: SLF001
            if attr.lower() in ['demand']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Demand):.6g}'
            elif attr.lower() in ['head', 'level']:
                value = (
                    f'{from_si(self.inp_units, val_si, HydParam.HydraulicHead):.6g}'
                )
            elif attr.lower() in ['flow']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Flow):.6g}'
            elif attr.lower() in ['pressure']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Pressure):.6g}'
            elif attr.lower() in ['setting']:
                if isinstance(action.target()[0], Valve):
                    if action.target()[0].valve_type.upper() in [
                        'PRV',
                        'PBV',
                        'PSV',
                    ]:
                        value = from_si(self.inp_units, val_si, HydParam.Pressure)
                    elif action.target()[0].valve_type.upper() in ['FCV']:
                        value = from_si(self.inp_units, val_si, HydParam.Flow)
                    else:
                        value = val_si
                else:
                    value = val_si
                value = f'{value:.6g}'
            else:  # status
                value = val_si
            if isinstance(action.target()[0], Valve):
                cls = 'Valve'
            elif isinstance(action.target()[0], Pump):
                cls = 'Pump'
            else:
                cls = action.target()[0].__class__.__name__
            clause = fmt.format(
                prefix, cls, action.target()[0].name, action.target()[1], value
            )
            self.add_then(clause)

    def add_else(self, clause):  # noqa: ANN001, ANN202
        """Add an "else/and" clause from an INP file"""  # noqa: D400, D415
        self._else_clauses.append(clause)

    def add_action_on_false(self, action, prefix=' ELSE'):  # noqa: ANN001, ANN202, C901, PLR0912
        """Add an "else" action from an IfThenElseControl"""  # noqa: D400, D415
        if isinstance(action, ControlAction):
            fmt = '{} {} {} {} = {}'
            attr = action._attribute  # noqa: SLF001
            val_si = action._repr_value()  # noqa: SLF001
            if attr.lower() in ['demand']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Demand):.6g}'
            elif attr.lower() in ['head', 'level']:
                value = (
                    f'{from_si(self.inp_units, val_si, HydParam.HydraulicHead):.6g}'
                )
            elif attr.lower() in ['flow']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Flow):.6g}'
            elif attr.lower() in ['pressure']:
                value = f'{from_si(self.inp_units, val_si, HydParam.Pressure):.6g}'
            elif attr.lower() in ['setting']:
                if isinstance(action.target()[0], Valve):
                    if action.target()[0].valve_type.upper() in [
                        'PRV',
                        'PBV',
                        'PSV',
                    ]:
                        value = from_si(self.inp_units, val_si, HydParam.Pressure)
                    elif action.target()[0].valve_type.upper() in ['FCV']:
                        value = from_si(self.inp_units, val_si, HydParam.Flow)
                    else:
                        value = val_si
                else:
                    value = val_si
                value = f'{value:.6g}'
            else:  # status
                value = val_si
            if isinstance(action.target()[0], Valve):
                cls = 'Valve'
            elif isinstance(action.target()[0], Pump):
                cls = 'Pump'
            else:
                cls = action.target()[0].__class__.__name__
            clause = fmt.format(
                prefix, cls, action.target()[0].name, action.target()[1], value
            )
            self.add_else(clause)

    def set_priority(self, priority):  # noqa: ANN001, ANN202
        self.priority = int(float(priority))

    def __str__(self):  # noqa: ANN204
        if self.priority >= 0:
            if len(self._else_clauses) > 0:
                return 'RULE {}\n{}\n{}\n{}\n PRIORITY {}\n ; end of rule\n'.format(
                    self.ruleID,
                    '\n'.join(self._if_clauses),
                    '\n'.join(self._then_clauses),
                    '\n'.join(self._else_clauses),
                    self.priority,
                )
            else:  # noqa: RET505
                return 'RULE {}\n{}\n{}\n PRIORITY {}\n ; end of rule\n'.format(
                    self.ruleID,
                    '\n'.join(self._if_clauses),
                    '\n'.join(self._then_clauses),
                    self.priority,
                )
        elif len(self._else_clauses) > 0:
            return 'RULE {}\n{}\n{}\n{}\n ; end of rule\n'.format(
                self.ruleID,
                '\n'.join(self._if_clauses),
                '\n'.join(self._then_clauses),
                '\n'.join(self._else_clauses),
            )
        else:
            return 'RULE {}\n{}\n{}\n ; end of rule\n'.format(
                self.ruleID,
                '\n'.join(self._if_clauses),
                '\n'.join(self._then_clauses),
            )

    def generate_control(self, model):  # noqa: ANN001, ANN202, C901, PLR0912, PLR0915
        condition_list = []
        for line in self._if_clauses:
            condition = None
            words = line.split()
            if words[1].upper() == 'SYSTEM':
                if words[2].upper() == 'DEMAND':
                    ### TODO: system demand  # noqa: FIX002, TD002, TD003
                    pass
                elif words[2].upper() == 'TIME':
                    condition = SimTimeCondition(
                        model, words[3], ' '.join(words[4:])
                    )
                else:
                    condition = TimeOfDayCondition(
                        model, words[3], ' '.join(words[4:])
                    )
            else:
                attr = words[3].lower()
                value = ValueCondition._parse_value(words[5])  # noqa: SLF001
                if attr.lower() in ['demand']:
                    value = to_si(self.inp_units, value, HydParam.Demand)
                elif attr.lower() in ['head'] or attr.lower() in ['level']:
                    value = to_si(self.inp_units, value, HydParam.HydraulicHead)
                elif attr.lower() in ['flow']:
                    value = to_si(self.inp_units, value, HydParam.Flow)
                elif attr.lower() in ['pressure']:
                    value = to_si(self.inp_units, value, HydParam.Pressure)
                elif attr.lower() in ['setting']:
                    link = model.get_link(words[2])
                    if isinstance(link, wntrfr.network.Pump):
                        value = value  # noqa: PLW0127
                    elif isinstance(link, wntrfr.network.Valve):
                        if link.valve_type.upper() in ['PRV', 'PBV', 'PSV']:
                            value = to_si(self.inp_units, value, HydParam.Pressure)
                        elif link.valve_type.upper() in ['FCV']:
                            value = to_si(self.inp_units, value, HydParam.Flow)
                if words[1].upper() in ['NODE', 'JUNCTION', 'RESERVOIR', 'TANK']:
                    condition = ValueCondition(
                        model.get_node(words[2]),
                        words[3].lower(),
                        words[4].lower(),
                        value,
                    )
                elif words[1].upper() in ['LINK', 'PIPE', 'PUMP', 'VALVE']:
                    condition = ValueCondition(
                        model.get_link(words[2]),
                        words[3].lower(),
                        words[4].lower(),
                        value,
                    )
                else:
                    ### FIXME: raise error  # noqa: FIX001, TD001, TD002, TD003
                    pass
            if words[0].upper() == 'IF' or words[0].upper() == 'AND':
                condition_list.append(condition)
            elif words[0].upper() == 'OR':
                if len(condition_list) > 0:
                    other = condition_list[-1]
                    condition_list.remove(other)
                else:
                    ### FIXME: raise error  # noqa: FIX001, TD001, TD002, TD003
                    pass
                conj = OrCondition(other, condition)
                condition_list.append(conj)
        final_condition = None
        for condition in condition_list:
            if final_condition is None:
                final_condition = condition
            else:
                final_condition = AndCondition(final_condition, condition)
        then_acts = []
        for act in self._then_clauses:
            words = act.strip().split()
            if len(words) < 6:  # noqa: PLR2004
                # TODO: raise error  # noqa: FIX002, TD002, TD003
                pass
            link = model.get_link(words[2])
            attr = words[3].lower()
            value = ValueCondition._parse_value(words[5])  # noqa: SLF001
            if attr.lower() in ['demand']:
                value = to_si(self.inp_units, value, HydParam.Demand)
            elif attr.lower() in ['head', 'level']:
                value = to_si(self.inp_units, value, HydParam.HydraulicHead)
            elif attr.lower() in ['flow']:
                value = to_si(self.inp_units, value, HydParam.Flow)
            elif attr.lower() in ['pressure']:
                value = to_si(self.inp_units, value, HydParam.Pressure)
            elif attr.lower() in ['setting']:  # noqa: SIM102
                if isinstance(link, Valve):
                    if link.valve_type.upper() in ['PRV', 'PBV', 'PSV']:
                        value = to_si(self.inp_units, value, HydParam.Pressure)
                    elif link.valve_type.upper() in ['FCV']:
                        value = to_si(self.inp_units, value, HydParam.Flow)
            then_acts.append(ControlAction(link, attr, value))
        else_acts = []
        for act in self._else_clauses:
            words = act.strip().split()
            if len(words) < 6:  # noqa: PLR2004
                # TODO: raise error  # noqa: FIX002, TD002, TD003
                pass
            link = model.get_link(words[2])
            attr = words[3].lower()
            value = ValueCondition._parse_value(words[5])  # noqa: SLF001
            if attr.lower() in ['demand']:
                value = to_si(self.inp_units, value, HydParam.Demand)
            elif attr.lower() in ['head', 'level']:
                value = to_si(self.inp_units, value, HydParam.HydraulicHead)
            elif attr.lower() in ['flow']:
                value = to_si(self.inp_units, value, HydParam.Flow)
            elif attr.lower() in ['pressure']:
                value = to_si(self.inp_units, value, HydParam.Pressure)
            elif attr.lower() in ['setting']:  # noqa: SIM102
                if isinstance(link, Valve):
                    if link.valve_type.upper() in ['PRV', 'PBV', 'PSV']:
                        value = to_si(self.inp_units, value, HydParam.Pressure)
                    elif link.valve_type.upper() in ['FCV']:
                        value = to_si(self.inp_units, value, HydParam.Flow)
            else_acts.append(ControlAction(link, attr, value))
        return Rule(
            final_condition,
            then_acts,
            else_acts,
            priority=self.priority,
            name=self.ruleID,
        )


class BinFile:
    """EPANET binary output file reader.

    This class provides read functionality for EPANET binary output files.

    Parameters
    ----------
    results_type : list of :class:`~wntrfr.epanet.util.ResultType`, default=None
        This parameter is *only* active when using a subclass of the BinFile that implements
            a custom reader or writer.
        If ``None``, then all results will be saved (node quality, demand, link flow, etc.).
        Otherwise, a list of result types can be passed to limit the memory used.
    network : bool, default=False
        Save a new WaterNetworkModel from the description in the output binary file. Certain
        elements may be missing, such as patterns and curves, if this is done.
    energy : bool, default=False
        Save the pump energy results.
    statistics : bool, default=False
        Save the statistics lines (different from the stats flag in the inp file) that are
        automatically calculated regarding hydraulic conditions.
    convert_status : bool, default=True
        Convert the EPANET link status (8 values) to simpler WNTR status (3 values). By
        default, this is done, and the encoded-cause status values are converted simple state
        values, instead.

    Returns
    -------
    :class:`~wntrfr.sim.results.SimulationResults`
        A WNTR results object will be created and added to the instance after read.

    """  # noqa: E501

    def __init__(  # noqa: ANN204, D107
        self,
        result_types=None,  # noqa: ANN001
        network=False,  # noqa: ANN001, FBT002
        energy=False,  # noqa: ANN001, FBT002
        statistics=False,  # noqa: ANN001, FBT002
        convert_status=True,  # noqa: ANN001, FBT002
    ):
        if os.name in ['nt', 'dos'] or sys.platform in ['darwin']:
            self.ftype = '=f4'
        else:
            self.ftype = '=f4'
        self.idlen = 32
        self.convert_status = convert_status
        self.hydraulic_id = None
        self.quality_id = None
        self.node_names = None
        self.link_names = None
        self.report_times = None
        self.flow_units = None
        self.pres_units = None
        self.mass_units = None
        self.quality_type = None
        self.num_nodes = None
        self.num_tanks = None
        self.num_links = None
        self.num_pumps = None
        self.num_valves = None
        self.report_start = None
        self.report_step = None
        self.duration = None
        self.chemical = None
        self.chem_units = None
        self.inp_file = None
        self.report_file = None
        self.results = wntrfr.sim.SimulationResults()
        if result_types is None:
            self.items = [member for name, member in ResultType.__members__.items()]
        else:
            self.items = result_types
        self.create_network = network
        self.keep_energy = energy
        self.keep_statistics = statistics

    def _get_time(self, t):  # noqa: ANN001, ANN202
        s = int(t)
        h = int(s / 3600)
        s -= h * 3600
        m = int(s / 60)
        s -= m * 60
        s = int(s)
        return f'{h:02}:{m:02}:{s:02}'

    def save_network_desc_line(self, element, values):  # noqa: ANN001, ANN201
        """Save network description meta-data and element characteristics.

        This method, by default, does nothing. It is available to be overloaded, but the
        core implementation assumes that an INP file exists that will have a better,
        human readable network description.

        Parameters
        ----------
        element : str
            The information being saved
        values : numpy.array
            The values that go with the information

        """  # noqa: E501

    def save_energy_line(self, pump_idx, pump_name, values):  # noqa: ANN001, ANN201
        """Save pump energy from the output file.

        This method, by default, does nothing. It is available to be overloaded
        in order to save information for pump energy calculations.

        Parameters
        ----------
        pump_idx : int
            the pump index
        pump_name : str
            the pump name
        values : numpy.array
            the values to save

        """

    def finalize_save(self, good_read, sim_warnings):  # noqa: ANN001, ANN201
        """Post-process data before writing results.

        This method, by default, does nothing. It is available to be overloaded
        in order to post process data.

        Parameters
        ----------
        good_read : bool
            was the full file read correctly
        sim_warnings : int
            were there warnings issued during the simulation

        """

    #    @run_lineprofile()
    def read(  # noqa: ANN201, C901, D417, PLR0912, PLR0915
        self, filename, convergence_error=False, darcy_weisbach=False, convert=True  # noqa: ANN001, FBT002
    ):
        """Read a binary file and create a results object.

        Parameters
        ----------
        filename : str
            An EPANET BIN output file
        convergence_error: bool (optional)
            If convergence_error is True, an error will be raised if the
            simulation does not converge. If convergence_error is False, partial results are returned,
            a warning will be issued, and results.error_code will be set to 0
            if the simulation does not converge.  Default = False.

        Returns
        -------
        object
            returns a WaterNetworkResults object

        """  # noqa: E501
        self.results = wntrfr.sim.SimulationResults()

        logger.debug('Read binary EPANET data from %s', filename)
        dt_str = 'u1'  # .format(self.idlen)
        with open(filename, 'rb') as fin:  # noqa: PTH123
            ftype = self.ftype
            idlen = self.idlen  # noqa: F841
            logger.debug('... read prolog information ...')
            prolog = np.fromfile(fin, dtype=np.int32, count=15)
            magic1 = prolog[0]
            version = prolog[1]
            nnodes = prolog[2]
            ntanks = prolog[3]
            nlinks = prolog[4]
            npumps = prolog[5]
            nvalve = prolog[6]
            wqopt = QualType(prolog[7])
            srctrace = prolog[8]
            flowunits = FlowUnits(prolog[9])
            presunits = PressureUnits(prolog[10])
            statsflag = StatisticsType(prolog[11])
            reportstart = prolog[12]
            reportstep = prolog[13]
            duration = prolog[14]
            logger.debug('EPANET/Toolkit version %d', version)
            logger.debug(
                'Nodes: %d; Tanks/Resrv: %d Links: %d; Pumps: %d; Valves: %d',
                nnodes,
                ntanks,
                nlinks,
                npumps,
                nvalve,
            )
            logger.debug(
                'WQ opt: %s; Trace Node: %s; Flow Units %s; Pressure Units %s',
                wqopt,
                srctrace,
                flowunits,
                presunits,
            )
            logger.debug(
                'Statistics: %s; Report Start %d, step %d; Duration=%d sec',
                statsflag,
                reportstart,
                reportstep,
                duration,
            )

            # Ignore the title lines
            np.fromfile(fin, dtype=np.uint8, count=240)
            inpfile = np.fromfile(fin, dtype=np.uint8, count=260)
            rptfile = np.fromfile(fin, dtype=np.uint8, count=260)
            chemical = bytes(
                np.fromfile(fin, dtype=dt_str, count=self.idlen)[:]
            ).decode(sys_default_enc)
            #            wqunits = ''.join([chr(f) for f in np.fromfile(fin, dtype=np.uint8, count=idlen) if f!=0 ])  # noqa: ERA001, E501
            wqunits = bytes(
                np.fromfile(fin, dtype=dt_str, count=self.idlen)[:]
            ).decode(sys_default_enc)
            mass = wqunits.split('/', 1)[0]
            if mass in ['mg', 'ug', 'mg', 'ug']:
                massunits = MassUnits[mass]
            else:
                massunits = MassUnits.mg
            self.flow_units = flowunits
            self.pres_units = presunits
            self.quality_type = wqopt
            self.mass_units = massunits
            self.num_nodes = nnodes
            self.num_tanks = ntanks
            self.num_links = nlinks
            self.num_pumps = npumps
            self.num_valves = nvalve
            self.report_start = reportstart
            self.report_step = reportstep
            self.duration = duration
            self.chemical = chemical
            self.chem_units = wqunits
            self.inp_file = inpfile
            self.report_file = rptfile
            nodenames = []
            linknames = []
            nodenames = [
                bytes(np.fromfile(fin, dtype=dt_str, count=self.idlen))
                .decode(sys_default_enc)
                .replace('\x00', '')
                for _ in range(nnodes)
            ]
            linknames = [
                bytes(np.fromfile(fin, dtype=dt_str, count=self.idlen))
                .decode(sys_default_enc)
                .replace('\x00', '')
                for _ in range(nlinks)
            ]
            self.node_names = np.array(nodenames)
            self.link_names = np.array(linknames)
            linkstart = np.array(  # noqa: F841
                np.fromfile(fin, dtype=np.int32, count=nlinks), dtype=int
            )
            linkend = np.array(  # noqa: F841
                np.fromfile(fin, dtype=np.int32, count=nlinks), dtype=int
            )
            linktype = np.fromfile(fin, dtype=np.int32, count=nlinks)
            tankidxs = np.fromfile(fin, dtype=np.int32, count=ntanks)  # noqa: F841
            tankarea = np.fromfile(fin, dtype=np.dtype(ftype), count=ntanks)  # noqa: F841
            elevation = np.fromfile(fin, dtype=np.dtype(ftype), count=nnodes)  # noqa: F841
            linklen = np.fromfile(fin, dtype=np.dtype(ftype), count=nlinks)  # noqa: F841
            diameter = np.fromfile(fin, dtype=np.dtype(ftype), count=nlinks)  # noqa: F841
            """
            self.save_network_desc_line('link_start', linkstart)
            self.save_network_desc_line('link_end', linkend)
            self.save_network_desc_line('link_type', linktype)
            self.save_network_desc_line('tank_node_index', tankidxs)
            self.save_network_desc_line('tank_area', tankarea)
            self.save_network_desc_line('node_elevation', elevation)
            self.save_network_desc_line('link_length', linklen)
            self.save_network_desc_line('link_diameter', diameter)
            """
            logger.debug('... read energy data ...')
            for i in range(npumps):  # noqa: B007
                pidx = int(np.fromfile(fin, dtype=np.int32, count=1))
                energy = np.fromfile(fin, dtype=np.dtype(ftype), count=6)
                self.save_energy_line(pidx, linknames[pidx - 1], energy)
            peakenergy = np.fromfile(fin, dtype=np.dtype(ftype), count=1)
            self.peak_energy = peakenergy

            logger.debug('... read EP simulation data ...')
            reporttimes = np.arange(
                reportstart,
                duration + reportstep - (duration % reportstep),
                reportstep,
            )
            nrptsteps = len(reporttimes)
            statsN = nrptsteps  # noqa: N806, F841
            if statsflag in [
                StatisticsType.Maximum,
                StatisticsType.Minimum,
                StatisticsType.Range,
            ]:
                nrptsteps = 1
                reporttimes = [reportstart + reportstep]
            self.num_periods = nrptsteps
            self.report_times = reporttimes

            # set up results metadata dictionary
            """
            if wqopt == QualType.Age:
                self.results.meta['quality_mode'] = 'AGE'
                self.results.meta['quality_units'] = 's'
            elif wqopt == QualType.Trace:
                self.results.meta['quality_mode'] = 'TRACE'
                self.results.meta['quality_units'] = '%'
                self.results.meta['quality_trace'] = srctrace
            elif wqopt == QualType.Chem:
                self.results.meta['quality_mode'] = 'CHEMICAL'
                self.results.meta['quality_units'] = wqunits
                self.results.meta['quality_chem'] = chemical
            self.results.time = reporttimes
            self.save_network_desc_line('report_times', reporttimes)
            self.save_network_desc_line('node_elevation', pd.Series(data=elevation, index=nodenames))
            self.save_network_desc_line('link_length', pd.Series(data=linklen, index=linknames))
            self.save_network_desc_line('link_diameter', pd.Series(data=diameter, index=linknames))
            self.save_network_desc_line('stats_mode', statsflag)
            self.save_network_desc_line('stats_N', statsN)
            nodetypes = np.array(['Junction']*self.num_nodes, dtype='|S10')
            nodetypes[tankidxs-1] = 'Tank'
            nodetypes[tankidxs[tankarea==0]-1] = 'Reservoir'
            linktypes = np.array(['Pipe']*self.num_links)
            linktypes[ linktype == EN.PUMP ] = 'Pump'
            linktypes[ linktype > EN.PUMP ] = 'Valve'
            self.save_network_desc_line('link_type', pd.Series(data=linktypes, index=linknames, copy=True))
            linktypes[ linktype == EN.CVPIPE ] = 'CV'
            linktypes[ linktype == EN.FCV ] = 'FCV'
            linktypes[ linktype == EN.PRV ] = 'PRV'
            linktypes[ linktype == EN.PSV ] = 'PSV'
            linktypes[ linktype == EN.PBV ] = 'PBV'
            linktypes[ linktype == EN.TCV ] = 'TCV'
            linktypes[ linktype == EN.GPV ] = 'GPV'
            self.save_network_desc_line('link_subtype', pd.Series(data=linktypes, index=linknames, copy=True))
            self.save_network_desc_line('node_type', pd.Series(data=nodetypes, index=nodenames, copy=True))
            self.save_network_desc_line('node_names', np.array(nodenames, dtype=str))
            self.save_network_desc_line('link_names', np.array(linknames, dtype=str))
            names = np.array(nodenames, dtype=str)
            self.save_network_desc_line('link_start', pd.Series(data=names[linkstart-1], index=linknames, copy=True))
            self.save_network_desc_line('link_end', pd.Series(data=names[linkend-1], index=linknames, copy=True))
            """  # noqa: E501

            #           type_list = 4*nnodes*['node'] + 8*nlinks*['link']  # noqa: ERA001
            name_list = nodenames * 4 + linknames * 8
            valuetype = (
                nnodes * ['demand']
                + nnodes * ['head']
                + nnodes * ['pressure']
                + nnodes * ['quality']
                + nlinks * ['flow']
                + nlinks * ['velocity']
                + nlinks * ['headloss']
                + nlinks * ['linkquality']
                + nlinks * ['linkstatus']
                + nlinks * ['linksetting']
                + nlinks * ['reactionrate']
                + nlinks * ['frictionfactor']
            )

            #           tuples = zip(type_list, valuetype, name_list)  # noqa: ERA001
            tuples = list(zip(valuetype, name_list))
            #                tuples = [(valuetype[i], v) for i, v in enumerate(name_list)]  # noqa: ERA001, E501
            index = pd.MultiIndex.from_tuples(tuples, names=['value', 'name'])

            try:
                data = np.fromfile(
                    fin,
                    dtype=np.dtype(ftype),
                    count=(4 * nnodes + 8 * nlinks) * nrptsteps,
                )
            except Exception as e:
                logger.exception('Failed to process file: %s', e)  # noqa: TRY401

            N = int(np.floor(len(data) / (4 * nnodes + 8 * nlinks)))  # noqa: N806
            if nrptsteps > N:
                t = reporttimes[N]
                if convergence_error:
                    logger.error(
                        'Simulation did not converge at time '  # noqa: G003
                        + self._get_time(t)
                        + '.'
                    )
                    raise RuntimeError(
                        'Simulation did not converge at time '
                        + self._get_time(t)
                        + '.'
                    )
                else:  # noqa: RET506
                    data = data[0 : N * (4 * nnodes + 8 * nlinks)]
                    data = np.reshape(data, (N, (4 * nnodes + 8 * nlinks)))
                    reporttimes = reporttimes[0:N]
                    warnings.warn(  # noqa: B028
                        'Simulation did not converge at time '
                        + self._get_time(t)
                        + '.'
                    )
                    self.results.error_code = wntrfr.sim.results.ResultsStatus.error
            else:
                data = np.reshape(data, (nrptsteps, (4 * nnodes + 8 * nlinks)))
                self.results.error_code = None

            df = pd.DataFrame(data.transpose(), index=index, columns=reporttimes)  # noqa: PD901
            df = df.transpose()  # noqa: PD901

            self.results.node = {}
            self.results.link = {}
            self.results.network_name = self.inp_file

            if convert:
                # Node Results
                self.results.node['demand'] = HydParam.Demand._to_si(  # noqa: SLF001
                    self.flow_units, df['demand']
                )
                self.results.node['head'] = HydParam.HydraulicHead._to_si(  # noqa: SLF001
                    self.flow_units, df['head']
                )
                self.results.node['pressure'] = HydParam.Pressure._to_si(  # noqa: SLF001
                    self.flow_units, df['pressure']
                )

                # Water Quality Results (node and link)
                if self.quality_type is QualType.Chem:
                    self.results.node['quality'] = QualParam.Concentration._to_si(  # noqa: SLF001
                        self.flow_units, df['quality'], mass_units=self.mass_units
                    )
                    self.results.link['quality'] = QualParam.Concentration._to_si(  # noqa: SLF001
                        self.flow_units,
                        df['linkquality'],
                        mass_units=self.mass_units,
                    )
                elif self.quality_type is QualType.Age:
                    self.results.node['quality'] = QualParam.WaterAge._to_si(  # noqa: SLF001
                        self.flow_units, df['quality'], mass_units=self.mass_units
                    )
                    self.results.link['quality'] = QualParam.WaterAge._to_si(  # noqa: SLF001
                        self.flow_units,
                        df['linkquality'],
                        mass_units=self.mass_units,
                    )
                else:
                    self.results.node['quality'] = df['quality']
                    self.results.link['quality'] = df['linkquality']

                # Link Results
                self.results.link['flowrate'] = HydParam.Flow._to_si(  # noqa: SLF001
                    self.flow_units, df['flow']
                )
                self.results.link['velocity'] = HydParam.Velocity._to_si(  # noqa: SLF001
                    self.flow_units, df['velocity']
                )

                headloss = np.array(df['headloss'])
                headloss[:, linktype < 2] = to_si(  # noqa: PLR2004
                    self.flow_units, headloss[:, linktype < 2], HydParam.HeadLoss  # noqa: PLR2004
                )  # Pipe or CV
                headloss[:, linktype >= 2] = to_si(  # noqa: PLR2004
                    self.flow_units, headloss[:, linktype >= 2], HydParam.Length  # noqa: PLR2004
                )  # Pump or Valve
                self.results.link['headloss'] = pd.DataFrame(
                    data=headloss, columns=linknames, index=reporttimes
                )

                status = np.array(df['linkstatus'])
                if self.convert_status:
                    status[status <= 2] = 0  # noqa: PLR2004
                    status[status == 3] = 1  # noqa: PLR2004
                    status[status >= 5] = 1  # noqa: PLR2004
                    status[status == 4] = 2  # noqa: PLR2004
                self.results.link['status'] = pd.DataFrame(
                    data=status, columns=linknames, index=reporttimes
                )

                setting = np.array(df['linksetting'])
                # pump setting is relative speed (unitless)
                setting[:, linktype == EN.PIPE] = to_si(
                    self.flow_units,
                    setting[:, linktype == EN.PIPE],
                    HydParam.RoughnessCoeff,
                    darcy_weisbach=darcy_weisbach,
                )
                setting[:, linktype == EN.PRV] = to_si(
                    self.flow_units,
                    setting[:, linktype == EN.PRV],
                    HydParam.Pressure,
                )
                setting[:, linktype == EN.PSV] = to_si(
                    self.flow_units,
                    setting[:, linktype == EN.PSV],
                    HydParam.Pressure,
                )
                setting[:, linktype == EN.PBV] = to_si(
                    self.flow_units,
                    setting[:, linktype == EN.PBV],
                    HydParam.Pressure,
                )
                setting[:, linktype == EN.FCV] = to_si(
                    self.flow_units, setting[:, linktype == EN.FCV], HydParam.Flow
                )
                self.results.link['setting'] = pd.DataFrame(
                    data=setting, columns=linknames, index=reporttimes
                )

                self.results.link['friction_factor'] = df['frictionfactor']
                self.results.link['reaction_rate'] = QualParam.ReactionRate._to_si(  # noqa: SLF001
                    self.flow_units, df['reactionrate'], self.mass_units
                )
            else:
                self.results.node['demand'] = df['demand']
                self.results.node['head'] = df['head']
                self.results.node['pressure'] = df['pressure']
                self.results.node['quality'] = df['quality']

                self.results.link['flowrate'] = df['flow']
                self.results.link['headloss'] = df['headloss']
                self.results.link['velocity'] = df['velocity']
                self.results.link['quality'] = df['linkquality']
                self.results.link['status'] = df['linkstatus']
                self.results.link['setting'] = df['linksetting']
                self.results.link['friction_factor'] = df['frictionfactor']
                self.results.link['reaction_rate'] = df['reactionrate']

            logger.debug('... read epilog ...')
            # Read the averages and then the number of periods for checks
            averages = np.fromfile(fin, dtype=np.dtype(ftype), count=4)
            self.averages = averages
            np.fromfile(fin, dtype=np.int32, count=1)
            warnflag = np.fromfile(fin, dtype=np.int32, count=1)
            magic2 = np.fromfile(fin, dtype=np.int32, count=1)
            if magic1 != magic2:
                logger.critical(
                    'The magic number did not match -- binary incomplete or incorrectly read. If you believe this file IS complete, please try a different float type. Current type is "%s"',  # noqa: E501
                    ftype,
                )
            # print numperiods, warnflag, magic
            if warnflag != 0:
                logger.warning('Warnings were issued during simulation')
        self.finalize_save(magic1 == magic2, warnflag)

        return self.results


class NoSectionError(Exception):  # noqa: D101
    pass


class _InpFileDifferHelper:  # pragma: no cover
    def __init__(self, f):  # noqa: ANN001, ANN204
        """Parameters
        ----------
        f: str

        """  # noqa: D205
        self._f = open(f)  # noqa: SIM115, PTH123
        self._num_lines = len(self._f.readlines())
        self._end = self._f.tell()
        self._f.seek(0)

    @property
    def f(self):  # noqa: ANN202
        return self._f

    def iter(self, start=0, stop=None, skip_section_headings=True):  # noqa: ANN001, ANN202, FBT002
        if stop is None:
            stop = self._end
        f = self.f
        f.seek(start)
        while f.tell() != stop:
            loc = f.tell()
            line = f.readline()
            if line.startswith(';'):
                continue
            if skip_section_headings:  # noqa: SIM102
                if line.startswith('['):
                    continue
            if len(line.split()) == 0:
                continue
            line = line.split(';')[0]
            yield loc, line

    def get_section(self, sec):  # noqa: ANN001, ANN202
        """Parameters
        ----------
        sec: str
            The section

        Returns
        -------
        start: int
            The starting point in the file for sec
        end: int
            The ending point in the file for sec

        """  # noqa: D205
        start = None
        end = None
        in_sec = False
        for loc, line in self.iter(0, None, skip_section_headings=False):
            line = line.split(';')[0]  # noqa: PLW2901
            if sec in line:
                start = loc
                in_sec = True
            elif '[' in line:
                if in_sec:
                    end = loc
                    in_sec = False
                    break
        if start is None:
            raise NoSectionError('Could not find section ' + sec)
        if end is None:
            end = self._end
        return start, end

    def contains_section(self, sec):  # noqa: ANN001, ANN202
        """Parameters
        ----------
        sec: str

        """  # noqa: D205
        try:
            self.get_section(sec)
            return True  # noqa: TRY300
        except NoSectionError:
            return False


def _convert_line(line):  # pragma: no cover  # noqa: ANN001, ANN202
    """Parameters
    ----------
    line: str

    Returns
    -------
    list

    """  # noqa: D205
    line = line.upper().split()
    tmp = []
    for i in line:
        if '.' in i:
            try:
                tmp.append(float(i))
            except:  # noqa: E722
                tmp.append(i)
        else:
            try:
                tmp.append(int(i))
            except:  # noqa: E722
                tmp.append(i)
    return tmp


def _compare_lines(line1, line2, tol=1e-14):  # pragma: no cover  # noqa: ANN001, ANN202
    """Parameters
    ----------
    line1: list of str
    line2: list of str

    Returns
    -------
    bool

    """  # noqa: D205
    if len(line1) != len(line2):
        return False

    for i, a in enumerate(line1):
        b = line2[i]
        if isinstance(a, (int, float)) or isinstance(a, int) and isinstance(b, int):
            if a != b:
                return False
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) > tol:
                return False
        elif a != b:
            return False

    return True


def _clean_line(wn, sec, line):  # pragma: no cover  # noqa: ANN001, ANN202
    """Parameters
    ----------
    wn: wntrfr.network.WaterNetworkModel
    sec: str
    line: list of str

    Returns
    -------
    new_list: list of str

    """  # noqa: D205
    if sec == '[JUNCTIONS]':  # noqa: SIM102
        if len(line) == 4:  # noqa: PLR2004
            other = wn.options.hydraulic.pattern
            if other is None:
                other = 1
            if isinstance(line[3], int) and isinstance(other, int):
                other = int(other)
            if line[3] == other:
                return line[:3]

    return line


def _read_control_line(line, wn, flow_units, control_name):  # noqa: ANN001, ANN202, C901, PLR0912, PLR0915
    """Parameters
    ----------
    line: str
    wn: wntrfr.network.WaterNetworkModel
    flow_units: str
    control_name: str

    Returns
    -------
    control_obj: Control

    """  # noqa: D205
    line = line.split(';')[0]
    current = line.split()
    if current == []:
        return None
    link_name = current[1]
    link = wn.get_link(link_name)
    if current[5].upper() != 'TIME' and current[5].upper() != 'CLOCKTIME':
        node_name = current[5]
    current = [i.upper() for i in current]
    current[1] = link_name  # don't capitalize the link name

    # Create the control action object

    status = current[2].upper()
    if (
        status == 'OPEN'  # noqa: PLR1714
        or status == 'OPENED'
        or status == 'CLOSED'
        or status == 'ACTIVE'
    ):
        setting = LinkStatus[status].value
        action_obj = wntrfr.network.ControlAction(link, 'status', setting)
    elif isinstance(link, wntrfr.network.Pump):
        action_obj = wntrfr.network.ControlAction(
            link, 'base_speed', float(current[2])
        )
    elif isinstance(link, wntrfr.network.Valve):
        if (
            link.valve_type == 'PRV'  # noqa: PLR1714
            or link.valve_type == 'PSV'
            or link.valve_type == 'PBV'
        ):
            setting = to_si(flow_units, float(current[2]), HydParam.Pressure)
        elif link.valve_type == 'FCV':
            setting = to_si(flow_units, float(current[2]), HydParam.Flow)
        elif link.valve_type == 'TCV':
            setting = float(current[2])
        elif link.valve_type == 'GPV':
            setting = current[2]
        else:
            raise ValueError(  # noqa: TRY003
                f'Unrecognized valve type {link.valve_type} while parsing control {line}'  # noqa: EM102, E501
            )
        action_obj = wntrfr.network.ControlAction(link, 'setting', setting)
    else:
        raise RuntimeError(
            f'Links of type {type(link)} can only have controls that change\n'  # noqa: ISC003
            + f'the link status. Control: {line}'
        )

    # Create the control object
    # control_count += 1  # noqa: ERA001
    # control_name = 'control '+str(control_count)  # noqa: ERA001
    if 'TIME' not in current and 'CLOCKTIME' not in current:
        threshold = None
        if 'IF' in current:
            node = wn.get_node(node_name)
            if current[6] == 'ABOVE':
                oper = np.greater
            elif current[6] == 'BELOW':
                oper = np.less
            else:
                raise RuntimeError(
                    'The following control is not recognized: ' + line
                )
            # OKAY - we are adding in the elevation. This is A PROBLEM
            # IN THE INP WRITER. Now that we know, we can fix it, but
            # if this changes, it will affect multiple pieces, just an
            # FYI.
            if node.node_type == 'Junction':
                threshold = to_si(
                    flow_units, float(current[7]), HydParam.Pressure
                )  # + node.elevation
                control_obj = Control._conditional_control(  # noqa: SLF001
                    node, 'pressure', oper, threshold, action_obj, control_name
                )
            elif node.node_type == 'Tank':
                threshold = to_si(
                    flow_units, float(current[7]), HydParam.HydraulicHead
                )  # + node.elevation
                control_obj = Control._conditional_control(  # noqa: SLF001
                    node, 'level', oper, threshold, action_obj, control_name
                )
        else:
            raise RuntimeError('The following control is not recognized: ' + line)
    #                control_name = ''  # noqa: ERA001
    #                for i in range(len(current)-1):
    #                    control_name = control_name + '/' + current[i]  # noqa: ERA001
    #                control_name = control_name + '/' + str(round(threshold, 2))  # noqa: ERA001
    elif 'CLOCKTIME' not in current:  # at time
        if 'TIME' not in current:
            raise ValueError(f'Unrecognized line in inp file: {line}')  # noqa: EM102, TRY003

        if ':' in current[5]:
            run_at_time = int(_str_time_to_sec(current[5]))
        else:
            run_at_time = int(float(current[5]) * 3600)
        control_obj = Control._time_control(  # noqa: SLF001
            wn, run_at_time, 'SIM_TIME', False, action_obj, control_name  # noqa: FBT003
        )
    #                    control_name = ''  # noqa: ERA001
    #                    for i in range(len(current)-1):
    #                        control_name = control_name + '/' + current[i]  # noqa: ERA001
    #                    control_name = control_name + '/' + str(run_at_time)  # noqa: ERA001
    else:  # at clocktime
        if len(current) < 7:  # noqa: PLR2004
            if ':' in current[5]:
                run_at_time = int(_str_time_to_sec(current[5]))
            else:
                run_at_time = int(float(current[5]) * 3600)
        else:
            run_at_time = int(_clock_time_to_sec(current[5], current[6]))
        control_obj = Control._time_control(  # noqa: SLF001
            wn, run_at_time, 'CLOCK_TIME', True, action_obj, control_name  # noqa: FBT003
        )
    #                    control_name = ''  # noqa: ERA001
    #                    for i in range(len(current)-1):
    #                        control_name = control_name + '/' + current[i]  # noqa: ERA001
    #                    control_name = control_name + '/' + str(run_at_time)  # noqa: ERA001
    return control_obj


def _diff_inp_files(  # noqa: ANN202, C901, PLR0912, PLR0915
    file1,  # noqa: ANN001
    file2=None,  # noqa: ANN001
    float_tol=1e-8,  # noqa: ANN001
    max_diff_lines_per_section=5,  # noqa: ANN001
    htmldiff_file='diff.html',  # noqa: ANN001
):  # pragma: no cover
    """Parameters
    ----------
    file1: str
    file2: str
    float_tol: float
    max_diff_lines_per_section: int
    htmldiff_file: str

    """  # noqa: D205
    wn = InpFile().read(file1)
    f1 = _InpFileDifferHelper(file1)
    if file2 is None:
        file2 = 'temp.inp'
        wn.write_inpfile(file2)
    f2 = _InpFileDifferHelper(file2)

    different_lines_1 = []
    different_lines_2 = []
    n = 0

    for section in _INP_SECTIONS:
        if not f1.contains_section(section):
            if f2.contains_section(section):
                print(f'\tfile1 does not contain section {section} but file2 does.')  # noqa: T201
            continue
        start1, stop1 = f1.get_section(section)
        start2, stop2 = f2.get_section(section)

        if section == '[PATTERNS]':
            new_lines_1 = []
            new_lines_2 = []
            label = None
            tmp_line = None
            tmp_loc = None
            for loc1, line1 in f1.iter(start1, stop1):
                tmp_label = line1.split()[0]
                if tmp_label != label:
                    if label is not None:
                        new_lines_1.append((tmp_loc, tmp_line))
                    tmp_loc = loc1
                    tmp_line = line1
                    label = tmp_label
                else:
                    tmp_line += ' ' + ' '.join(line1.split()[1:])
            if tmp_line is not None:
                new_lines_1.append((tmp_loc, tmp_line))
            label = None
            tmp_line = None
            tmp_loc = None
            for loc2, line2 in f2.iter(start2, stop2):
                tmp_label = line2.split()[0]
                if tmp_label != label:
                    if label is not None:
                        new_lines_2.append((tmp_loc, tmp_line))
                    tmp_loc = loc2
                    tmp_line = line2
                    label = tmp_label
                else:
                    tmp_line += ' ' + ' '.join(line2.split()[1:])
            if tmp_line is not None:
                new_lines_2.append((tmp_loc, tmp_line))
        else:
            new_lines_1 = list(f1.iter(start1, stop1))
            new_lines_2 = list(f2.iter(start2, stop2))

        different_lines_1.append(section)
        different_lines_2.append(section)

        if len(new_lines_1) != len(new_lines_2):
            assert len(different_lines_1) == len(different_lines_2)  # noqa: S101
            n1 = 0
            n2 = 0
            for loc1, line1 in new_lines_1:  # noqa: B007
                different_lines_1.append(line1)
                n1 += 1
            for loc2, line2 in new_lines_2:  # noqa: B007
                different_lines_2.append(line2)
                n2 += 1
            if n1 > n2:
                n = n1 - n2
                for i in range(n):  # noqa: B007
                    different_lines_2.append('')  # noqa: PERF401
            elif n2 > n1:
                n = n2 - n1
                for i in range(n):  # noqa: B007
                    different_lines_1.append('')  # noqa: PERF401
            else:
                raise RuntimeError('Unexpected')  # noqa: EM101
            continue

        section_line_counter = 0
        f2_iter = iter(new_lines_2)
        for loc1, line1 in new_lines_1:  # noqa: B007
            orig_line_1 = line1
            loc2, line2 = next(f2_iter)
            orig_line_2 = line2
            line1 = _convert_line(line1)  # noqa: PLW2901
            line2 = _convert_line(line2)
            line1 = _clean_line(wn, section, line1)  # noqa: PLW2901
            line2 = _clean_line(wn, section, line2)
            if not _compare_lines(line1, line2, tol=float_tol):
                if section_line_counter < max_diff_lines_per_section:
                    section_line_counter = section_line_counter + 1
                else:
                    break
                different_lines_1.append(orig_line_1)
                different_lines_2.append(orig_line_2)

    if len(different_lines_1) < 200:  # If lines < 200 use difflib  # noqa: PLR2004
        differ = difflib.HtmlDiff()
        html_diff = differ.make_file(different_lines_1, different_lines_2)
    else:  # otherwise, create a simple html file
        differ_df = pd.DataFrame(
            [different_lines_1, different_lines_2], index=[file1, file2]
        ).transpose()
        html_diff = differ_df.to_html()

    g = open(htmldiff_file, 'w')  # noqa: SIM115, PTH123
    g.write(html_diff)
    g.close()

    return n
