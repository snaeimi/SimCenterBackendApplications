# -*- coding: utf-8 -*-  # noqa: INP001, D100, UP009
# Copyright (c) 2016-2017, The Regents of the University of California (Regents).
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are those
# of the authors and should not be interpreted as representing official policies,
# either expressed or implied, of the FreeBSD Project.
#
# REGENTS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.
# THE SOFTWARE AND ACCOMPANYING DOCUMENTATION, IF ANY, PROVIDED HEREUNDER IS
# PROVIDED "AS IS". REGENTS HAS NO OBLIGATION TO PROVIDE MAINTENANCE, SUPPORT,
# UPDATES, ENHANCEMENTS, OR MODIFICATIONS.

#
# Contributors:
# Abiy Melaku


#
# This script reads OpenFOAM output and plot the characteristics of the
# approaching wind. For now, it read and plots only velocity field data and
# pressure on predicted set of probes.
#

import sys  # noqa: I001
import os
import subprocess
import json
import stat
import shutil
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec  # noqa: PLR0402
from scipy import signal
from scipy.interpolate import interp1d
from scipy.interpolate import UnivariateSpline
from scipy import stats
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import argparse
import re


def read_bin_forces(fileName):  # noqa: C901, N803
    """
    Reads binData measured at the center of each bin.

    Reads force data integrated over a surface from Open file and returns
    bin heights, time, and the forces and moments vector on the bins for each
    time step.

    """  # noqa: D401
    forces = []
    moments = []
    time = []
    nbins = 0

    with open(fileName, 'r') as f:  # noqa: PTH123, UP015
        for line in f:
            if line.startswith('#'):
                # Read the origin where the force are integrated
                if line.startswith('# bins'):
                    line = line.replace('# bins', '')  # noqa: PLW2901
                    line = line.replace(':', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    nbins = int(line[0])
                    coords = np.zeros((nbins, 3))
                elif line.startswith('# x co-ords'):
                    line = line.replace('# x co-ords', '')  # noqa: PLW2901
                    line = line.replace(':', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    for i in range(nbins):
                        coords[i, 0] = line[i]
                elif line.startswith('# y co-ords'):
                    line = line.replace('# y co-ords', '')  # noqa: PLW2901
                    line = line.replace(':', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    for i in range(nbins):
                        coords[i, 1] = line[i]
                elif line.startswith('# z co-ords'):
                    line = line.replace('# z co-ords', '')  # noqa: PLW2901
                    line = line.replace(':', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    for i in range(nbins):
                        coords[i, 2] = line[i]
                else:
                    continue

            # Read only the pressure part
            else:
                line = line.replace('(', '')  # noqa: PLW2901
                line = line.replace(')', '')  # noqa: PLW2901
                line = line.split()  # noqa: PLW2901
                time.append(float(line[0]))
                story_force = np.zeros((nbins, 3))
                story_moments = np.zeros((nbins, 3))
                for i in range(nbins):
                    start = 12 * i + 1

                    # Take only pressure part
                    story_force[i, 0] = line[start]
                    story_force[i, 1] = line[start + 1]
                    story_force[i, 2] = line[start + 2]

                    story_moments[i, 0] = line[start + 6]
                    story_moments[i, 1] = line[start + 6 + 1]
                    story_moments[i, 2] = line[start + 6 + 2]

                forces.append(story_force)
                moments.append(story_moments)

    time = np.asarray(time, dtype=np.float32)
    forces = np.asarray(forces, dtype=np.float32)
    moments = np.asarray(moments, dtype=np.float32)

    return coords, time, forces, moments


def read_forces(fileName):  # noqa: N803
    """
    Reads force data integrated over a surface from OpenFOAM file and returns
    origin(center of rotation), time, and the forces and moments vector for
    each time step.

    """  # noqa: D205, D401
    origin = np.zeros(3)
    forces = []
    moments = []
    time = []

    with open(fileName, 'r') as f:  # noqa: PTH123, UP015
        for line in f:
            if line.startswith('#'):
                # Read the origin where the force are integrated
                if line.startswith('# CofR'):
                    line = line.replace('(', '')  # noqa: PLW2901
                    line = line.replace(')', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    origin[0] = line[3]  # x-coordinate
                    origin[1] = line[4]  # y-coordinate
                    origin[2] = line[5]  # z-coordinate
                else:
                    continue
            # Read only the pressure part of force and moments.
            # Viscous and porous are ignored
            else:
                line = line.replace('(', '')  # noqa: PLW2901
                line = line.replace(')', '')  # noqa: PLW2901
                line = line.split()  # noqa: PLW2901
                time.append(float(line[0]))
                forces.append([float(line[1]), float(line[2]), float(line[3])])
                moments.append(
                    [float(line[1 + 9]), float(line[2 + 9]), float(line[3 + 9])]
                )

    time = np.asarray(time, dtype=np.float32)
    forces = np.asarray(forces, dtype=np.float32)
    moments = np.asarray(moments, dtype=np.float32)

    return origin, time, forces, moments


def readPressureProbes(fileName):  # noqa: N802, N803
    """
    Created on Wed May 16 14:31:42 2018

    Reads pressure probe data from OpenFOAM and return the probe location, time, and the pressure
    for each time step.

    @author: Abiy
    """  # noqa: D400, D401
    probes = []
    p = []
    time = []

    with open(fileName, 'r') as f:  # noqa: PTH123, UP015
        for line in f:
            if line.startswith('#'):
                if line.startswith('# Probe'):
                    line = line.replace('(', '')  # noqa: PLW2901
                    line = line.replace(')', '')  # noqa: PLW2901
                    line = line.split()  # noqa: PLW2901
                    probes.append([float(line[3]), float(line[4]), float(line[5])])
                else:
                    continue
            else:
                line = line.split()  # noqa: PLW2901
                time.append(float(line[0]))
                p_probe_i = np.zeros([len(probes)])
                for i in range(len(probes)):
                    p_probe_i[i] = float(line[i + 1])
                p.append(p_probe_i)

    probes = np.asarray(probes, dtype=np.float32)
    time = np.asarray(time, dtype=np.float32)
    p = np.asarray(p, dtype=np.float32)

    return probes, time, p


def read_pressure_data(file_names):
    """
    This functions takes names of different OpenFOAM pressure measurements and connect
    them into one file removing overlaps if any. All the probes must be in the same
    location, otherwise an error might show up.

    Parameters
    ----------
    *args
        List of file pashes of pressure data to be connected together.

    Returns
    -------
    time, pressure
        Returns the pressure time and pressure data of the connected file.
    """  # noqa: D205, D401, D404
    no_files = len(file_names)
    connected_time = []  # Connected array of time
    connected_p = []  # connected array of pressure.

    time1 = []
    p1 = []
    time2 = []
    p2 = []
    probes = []

    for i in range(no_files):
        probes, time2, p2 = readPressureProbes(file_names[i])

        if i == 0:
            connected_time = time2
            connected_p = p2
        else:
            try:
                index = np.where(time2 > time1[-1])[0][0]
                # index += 1

            except:  # noqa: E722
                # sys.exit('Fatal Error!: the pressure filese have time gap')
                index = 0  # Joint them even if they have a time gap

            connected_time = np.concatenate((connected_time, time2[index:]))
            connected_p = np.concatenate((connected_p, p2[index:]))

        time1 = time2
        p1 = p2  # noqa: F841
    return probes, connected_time, connected_p


class PressureData:
    """
    A class that holds a pressure data and performs the following operations:
            - mean and rms pressure coefficients
            - peak pressure coefficients
    """  # noqa: D205, D400

    def __init__(
        self, path, u_ref=0.0, rho=1.25, p_ref=0.0, start_time=None, end_time=None
    ):
        self.path = path
        self.u_ref = u_ref
        self.p_ref = p_ref
        self.rho = rho
        self.start_time = start_time
        self.end_time = end_time
        self.read_cfd_data()
        self.set_time()
        self.Nt = len(self.time)
        self.T = self.time[-1]
        self.z = self.probes[:, 2]
        self.y = self.probes[:, 1]
        self.x = self.probes[:, 0]
        self.dt = np.mean(np.diff(self.time))
        self.probe_count = np.shape(self.probes)[0]

    def read_cfd_data(self):  # noqa: D102
        if os.path.isdir(self.path):  # noqa: PTH112
            print('Reading from path : %s' % (self.path))  # noqa: T201, UP031
            time_names = os.listdir(self.path)
            sorted_index = np.argsort(np.float_(time_names)).tolist()  # noqa: NPY201
            # print(sorted_index)
            # print("\tTime directories: %s" %(time_names))
            file_names = []

            for i in range(len(sorted_index)):
                file_name = os.path.join(self.path, time_names[sorted_index[i]], 'p')  # noqa: PTH118
                file_names.append(file_name)

            # print(file_names)
            self.probes, self.time, self.p = read_pressure_data(file_names)
            self.p = self.rho * np.transpose(self.p)  # OpenFOAM gives p/rho
            p_dyn = 0.5 * self.rho * self.u_ref**2.0

            if self.u_ref != 0.0:
                self.cp = self.p / p_dyn

            # self.p = np.transpose(self.p) # OpenFOAM gives p/rho
        else:
            print('Cannot find the file path: %s' % (self.path))  # noqa: T201, UP031

    def set_time(self):  # noqa: D102
        if self.start_time != None:  # noqa: E711
            start_index = int(np.argmax(self.time > self.start_time))
            self.time = self.time[start_index:]
            # self.cp = self.cp[:,start_index:]
            try:
                self.p = self.p[:, start_index:]
                self.cp = self.cp[:, start_index:]
            except:  # noqa: S110, E722
                pass

        if self.end_time != None:  # noqa: E711
            end_index = int(np.argmax(self.time > self.end_time))
            self.time = self.time[:end_index]
            # self.cp = self.cp[:,:end_index]
            try:
                self.p = self.p[:, :end_index]
                self.cp = self.cp[:, :end_index]
            except:  # noqa: S110, E722
                pass


if __name__ == '__main__':
    """"
    Entry point to read the simulation results from OpenFOAM case and post-process it.
    """

    # CLI parser
    parser = argparse.ArgumentParser(
        description='Get EVENT file from OpenFOAM output'
    )
    parser.add_argument(
        '-c', '--case', help='OpenFOAM case directory', required=True
    )

    arguments, unknowns = parser.parse_known_args()

    case_path = arguments.case
    # case_path = "C:\\Users\\fanta\\Documents\\WE-UQ\\LocalWorkDir\\IsolatedBuildingCFD"

    print('Case full path: ', case_path)  # noqa: T201

    # Read JSON data
    json_path = os.path.join(  # noqa: PTH118
        case_path, 'constant', 'simCenter', 'input', 'IsolatedBuildingCFD.json'
    )
    with open(json_path) as json_file:  # noqa: PTH123
        json_data = json.load(json_file)

    # Returns JSON object as a dictionary
    rm_data = json_data['resultMonitoring']
    wc_data = json_data['windCharacteristics']
    duration = json_data['numericalSetup']['duration']

    load_output_path = os.path.join(  # noqa: PTH118
        case_path, 'constant', 'simCenter', 'output', 'windLoads'
    )

    # Check if it exists and remove files
    if os.path.exists(load_output_path):  # noqa: PTH110
        shutil.rmtree(load_output_path)

    # Create new path
    Path(load_output_path).mkdir(parents=True, exist_ok=True)

    # Read and write the story forces
    force_file_name = os.path.join(  # noqa: PTH118
        case_path, 'postProcessing', 'storyForces', '0', 'forces_bins.dat'
    )
    origin, time, forces, moments = read_bin_forces(force_file_name)
    start_time = 1000
    time = time[start_time:]
    forces = forces[start_time:, :, :]
    moments = moments[start_time:, :, :]

    print(force_file_name)  # noqa: T201

    num_times = len(time)
    num_stories = rm_data['numStories']

    storyLoads = np.zeros((num_times, num_stories * 3 + 1))  # noqa: N816

    storyLoads[:, 0] = time

    for i in range(num_stories):
        storyLoads[:, 3 * i + 1] = forces[:, i, 0]
        storyLoads[:, 3 * i + 2] = forces[:, i, 1]
        storyLoads[:, 3 * i + 3] = moments[:, i, 2]

    np.savetxt(
        os.path.join(load_output_path, 'storyLoad.txt'),  # noqa: PTH118
        storyLoads,
        delimiter='\t',
    )

    # Write base loads
    if rm_data['monitorBaseLoad']:
        force_file_name = os.path.join(  # noqa: PTH118
            case_path, 'postProcessing', 'baseForces', '0', 'forces.dat'
        )
        origin, time, forces, moments = read_forces(force_file_name)

        time = time[start_time:]
        forces = forces[start_time:, :]
        moments = moments[start_time:, :]

        print(force_file_name)  # noqa: T201

        num_times = len(time)

        baseLoads = np.zeros((num_times, 3 * 2 + 1))  # noqa: N816

        baseLoads[:, 0] = time
        baseLoads[:, 1:4] = forces
        baseLoads[:, 4:7] = moments

        np.savetxt(
            os.path.join(load_output_path, 'baseLoad.txt'),  # noqa: PTH118
            baseLoads,
            delimiter='\t',
        )

    # Write base loads
    if rm_data['monitorSurfacePressure']:
        p_file_name = ''
        if rm_data['importPressureSamplingPoints']:
            p_file_name = os.path.join(  # noqa: PTH118
                case_path, 'postProcessing', 'importedPressureSamplingPoints'
            )
        else:
            p_file_name = os.path.join(  # noqa: PTH118
                case_path, 'postProcessing', 'generatedPressureSamplingPoints'
            )

        wind_speed = wc_data['referenceWindSpeed']
        print(p_file_name)  # noqa: T201

        cfd_p = PressureData(
            p_file_name,
            u_ref=wind_speed,
            rho=1.25,
            p_ref=0.0,
            start_time=duration * 0.1,
            end_time=None,
        )

        num_times = len(cfd_p.time)

        pressureData = np.zeros((num_times, cfd_p.probe_count + 1))  # noqa: N816

        pressureData[:, 0] = cfd_p.time
        pressureData[:, 1:] = np.transpose(cfd_p.cp)

        np.savetxt(
            os.path.join(load_output_path, 'pressureData.txt'),  # noqa: PTH118
            pressureData,
            delimiter='\t',
        )
