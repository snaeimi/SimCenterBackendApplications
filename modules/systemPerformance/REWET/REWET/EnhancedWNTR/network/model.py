"""The wntrfr.network.model module includes methods to build a water network
model.

.. rubric:: Contents

.. autosummary::

    WaterNetworkModel
    PatternRegistry
    CurveRegistry
    SourceRegistry
    NodeRegistry
    LinkRegistry

"""  # noqa: D205

import logging
import math
from collections import OrderedDict

import numpy as np
from wntrfr.network import WaterNetworkModel
from wntrfr.network.base import LinkStatus
from wntrfr.network.elements import Pump, Valve

from ..epanet.io import InpFile  # noqa: TID252

logger = logging.getLogger(__name__)


class WaterNetworkModel(WaterNetworkModel):
    """Water network model class.

    Parameters
    ----------
    inp_file_name: string (optional)
        Directory and filename of EPANET inp file to load into the
        WaterNetworkModel object.

    """

    def __init__(self, inp_file_name=None):
        super().__init__(inp_file_name)
        self.breakage_link = {}
        self.expicit_leak = []

    def updateWaterNetworkModelWithResult(  # noqa: C901, N802
        self,
        result,
        registry,  # noqa: ARG002
        latest_simulation_time=None,
    ):
        """Updates Water Network Model consistent with result model. must be only
        used with EPANET solver or just in case you really know what you are
        doing.

        Parameters
        ----------
        result : Water Network Result

        latest_simulation_time : int
            latest time of simulation(duration of the latest run), to be
            checked with time in result. Defaylt None.

        Raises
        ------
        ValueError
            When simulation object is not of type EpanetSimulator
            When latest simulation time is provided and is not consistent with
            latest time in result.
            When Tank level gets less than zero


        Returns
        -------
        None.

        """  # noqa: D205, D401, DOC202, RUF100
        max_time = result.node['head'].index.max()
        if latest_simulation_time == None:  # noqa: E711
            latest_simulation_time = max_time
        elif latest_simulation_time != max_time:
            raise ValueError(  # noqa: TRY003
                'Provided LATEST SIMULATION TIME id not consistent with the latest time in RESULT'  # noqa: EM101
            )

        avilable_tank_name_list = set(self.tank_name_list).intersection(
            result.node['head'].columns
        )
        for tank_name in avilable_tank_name_list:
            # if tank_name not in result.node['head'].columns:
            # continue
            tank_level = None
            head = None

            cur_node = self.get_node(tank_name)
            if cur_node._is_isolated:  # noqa: SLF001
                continue
            head = result.node['head'].loc[max_time, tank_name]

            tank_level = head - cur_node.elevation
            tank_level = max(tank_level, 0)

            tank_level = max(tank_level, cur_node.min_level)

            if tank_level - cur_node.max_level > 0:
                tank_level = cur_node.max_level

            cur_node.init_level = abs(tank_level)
            cur_node._head = cur_node.elevation + tank_level  # noqa: SLF001

            if tank_level < 0.0:
                logger.error('head= ' + repr(head))  # noqa: G003
                logger.error('elevation= ' + repr(cur_node.elevation))  # noqa: G003
                logger.error('tank_level= ' + repr(tank_level))  # noqa: G003
                raise ValueError(
                    'Tank Level for ' + tank_name + ' is less than zero'
                )

        for link_name in self.link_name_list:
            link = self.get_link(link_name)
            setting = None
            status = None
            try:
                setting = result.link['setting'].loc[max_time, link_name]
                status = result.link['status'].loc[max_time, link_name]
            except:  # noqa: S112, E722
                # logger.error(link_name + ' exist in WaterNetwork but does not exist in result')
                # raise ValueError(link_name + ' exist in WaterNetwork but does not exist in result')
                continue

            if isinstance(link, Valve):
                link.settings = float(setting)

            elif isinstance(link, Pump):
                link.setting.base_value = float(setting)

            if status == 0:
                link._user_status = LinkStatus.Closed  # noqa: SLF001

            elif status == 1:
                link._user_status = LinkStatus.Open  # noqa: SLF001

            elif status == 2:  # noqa: PLR2004
                link._user_status = LinkStatus.Active  # noqa: SLF001

            else:
                logger.error('Element type is: ' + repr(type(link)))  # noqa: G003
                logger.error('Status is : ' + repr(status))  # noqa: G003

    def read_inpfile(self, filename):
        """Defines water network model components from an EPANET INP file

        Parameters
        ----------
        filename : string
            Name of the INP file.

        """  # noqa: D400, D401
        inpfile = InpFile()
        inpfile.read(filename, wn=self)
        self._inpfile = inpfile

    def write_inpfile(self, filename, units=None):
        """Writes the current water network model to an EPANET INP file

        Parameters
        ----------
        filename : string
            Name of the inp file.
        units : str, int or FlowUnits
            Name of the units being written to the inp file.

        """  # noqa: D400, D401
        if self._inpfile is None:
            logger.warning(
                'Writing a minimal INP file without saved non-WNTR options (energy, etc.)'
            )
            self._inpfile = InpFile()
        if units is None:
            units = self._options.hydraulic.en2_units
        self._inpfile.write(filename, self, units=units)

    def implicitLeakToExplicitEMitter(self, registry):  # noqa: N802, D102
        if len(self.expicit_leak) > 0:
            raise ValueError('Explicit leak is not reset')  # noqa: EM101, TRY003

        registry.active_pipe_damages = OrderedDict()
        for node_name in self.node_name_list:
            node = self.get_node(node_name)

            if node._leak:  # noqa: SLF001
                if node_name in self.expicit_leak:
                    raise ValueError(
                        'The node name in already in leak memory: ' + node_name
                    )

                new_node_name = node_name + '-nn'
                new_coord = (node.coordinates[0] + 1, node.coordinates[1] + 1)
                self.add_junction(
                    new_node_name, elevation=node.elevation, coordinates=new_coord
                )
                new_node = self.get_node(new_node_name)

                new_pipe_name = node_name + '-elk'
                self.add_pipe(
                    new_pipe_name,
                    node_name,
                    new_node_name,
                    diameter=100,
                    length=1,
                    roughness=1000000,
                    check_valve=True,
                )

                cd = node.leak_area * (2) ** 0.5  # (m^3ps/(KPa^0.5))
                cd = cd / (0.145038**0.5)  # (gpm/(Psi^0.5))
                # When writing to emitter, function from_si changes m^3ps to GPM

                new_node._emitter_coefficient = cd  # noqa: SLF001

                if node.demand_timeseries_list[0].base_value > 0.001:  # noqa: PLR2004
                    raise ValueError('leak node has demand: ' + node_name)
                temp = {
                    'node_name': node_name,
                    'method': 'emitter',
                    'element1': new_pipe_name,
                    'element2': new_node_name,
                    'attr1': cd,
                }
                self.expicit_leak.append(temp)
                registry.explicit_leak_node[node_name] = new_node_name
                registry.active_pipe_damages.update({new_node_name: node_name})

    def implicitLeakToExplicitReservoir(self, registry):  # noqa: N802, D102
        if len(self.expicit_leak) > 0:
            raise ValueError('Explicit leak is not reset')  # noqa: EM101, TRY003
        registry.active_pipe_damages = OrderedDict()
        for node_name in self.node_name_list:
            node = self.get_node(node_name)

            if node._leak:  # noqa: SLF001
                if node_name in self.expicit_leak:
                    raise ValueError(
                        'The node name in already in leak memory: ' + node_name
                    )

                new_node_name = node_name + '_nn'
                new_coord = (node.coordinates[0] + 1, node.coordinates[1] + 1)
                self.add_reservoir(
                    new_node_name, base_head=node.elevation, coordinates=new_coord
                )

                new_pipe_name = node_name + '-rlk'
                diameter = np.sqrt(node.leak_area * 4 / math.pi)
                self.add_pipe(
                    new_pipe_name,
                    node_name,
                    new_node_name,
                    diameter=diameter,
                    length=1,
                    roughness=1000000,
                    minor_loss=1,
                    check_valve=True,
                )

                if node.demand_timeseries_list[0].base_value > 0.001:  # noqa: PLR2004
                    raise ValueError('leak node has demand: ' + node_name)
                temp = {
                    'node_name': node_name,
                    'method': 'reservoir',
                    'element1': new_pipe_name,
                    'element2': new_node_name,
                }
                self.expicit_leak.append(temp)
                registry.explicit_leak_node[node_name] = new_node_name
                registry.active_pipe_damages.update({new_node_name: node_name})

    def resetExplicitLeak(self):  # noqa: N802, D102
        for data in self.expicit_leak:
            new_pipe_name = data['element1']
            new_node_name = data['element2']

            self.remove_link(new_pipe_name, force=True)
            self.get_node(new_node_name)._emitter_coefficient = None  # noqa: SLF001
            self.remove_node(new_node_name, force=True)

        self.expicit_leak = []

    def linkBreackage(self, registry):  # noqa: N802, D102
        if len(self.breakage_link) > 0:
            raise ValueError('Breakckage is not unliked')  # noqa: EM101, TRY003

        self.breakage_link = {}
        pipe_damage_table = registry.getDamageData('PIPE')
        broken_pipe_damage_table = pipe_damage_table[
            pipe_damage_table['damage_type'] == 'break'
        ]

        for damage_node, row in broken_pipe_damage_table.iterrows():  # noqa: B007
            if registry.getPipeDamageAttribute('repair', damage_node) == True:  # noqa: E712
                continue
            pipe_A, pipe_B, orginal_pipe, node_A, node_B = registry.getBreakData(  # noqa: N806
                damage_node
            )

            pipe_name_list = self.pipe_name_list
            junction_name_list = self.junction_name_list

            iPipe_A_in = pipe_A in pipe_name_list  # noqa: N806
            iPipe_B_in = pipe_B in pipe_name_list  # noqa: N806
            iNode_A_in = node_A in junction_name_list  # noqa: N806
            iNode_B_in = node_B in junction_name_list  # noqa: N806

            if not iPipe_A_in or not iPipe_B_in or not iNode_A_in or not iNode_B_in:
                if iPipe_A_in or iPipe_B_in or iNode_A_in or iNode_B_in:
                    raise ValueError(
                        'The damage is partially removed?: '
                        + repr(iPipe_A_in)
                        + ', '
                        + repr(iPipe_B_in)
                        + ', '
                        + repr(iNode_A_in)
                        + ', '
                        + repr(iNode_B_in)
                        + ', '
                        + repr(damage_node)
                    )
            else:
                node1 = self.get_link(pipe_A).start_node
                node2 = self.get_link(pipe_B).end_node

                new_pipe_name = damage_node + '_BLP'
                self.add_pipe(
                    new_pipe_name,
                    node1.name,
                    node2.name,
                    length=1,
                    diameter=1 * 2.54 / 100,
                    roughness=100,
                )
                self.breakage_link[damage_node] = new_pipe_name

    def unlinkBreackage(self):  # noqa: N802, D102
        for damage_node, link_pipe_name in self.breakage_link.items():  # noqa: B007, PERF102
            self.remove_link(link_pipe_name, force=True)

        self.breakage_link = {}
