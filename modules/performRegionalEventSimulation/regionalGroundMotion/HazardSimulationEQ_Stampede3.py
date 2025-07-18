import ujson as json
import os
import sys
import pickle
from tqdm import tqdm
import numpy as np
import subprocess
import shlex
from mpi4py import MPI
import socket
import geopandas as gpd
from pathlib import Path
from LoadRupFile import load_earthquake_rupFile

# Generated by chatGPT to check if a string is a valid path format.
def is_valid_path_format(string):
    try:
        path = Path(string)
        return path.is_absolute() or len(path.parts) > 1
    except ValueError:
        return False

if __name__ == '__main__':
    ## input:
    input_dir = os.environ['inputDir']
    work_dir = os.environ['outputDir']
    hazard_config_file = os.path.join(input_dir, 'EQHazardConfiguration.json')
    with open(hazard_config_file, 'r') as f:
        hazard_info = json.load(f)
    python_path = os.environ['PYTHON_LOC']
    python_path = os.path.join(python_path, 'bin','python3')
    rup_file = os.path.join(input_dir, 'RupFile.geojson')
    sites_file = os.path.join(input_dir, 'SimCenterSiteModel.csv')

    file_path = os.path.dirname(os.path.realpath(__file__))
    calculation_single_process_file = os.path.join(file_path, 'calculation_single_proc.py')
    
    # Update some paths used in the hazard_info
    hazard_info['Scenario']['sourceFile'] = rup_file
    hazard_info['Site']['siteFile'] = sites_file
    hazard_info['Directory'] = work_dir
    
    if 'GroundFailure' in hazard_info['Event'].keys():  # noqa: SIM118
        ground_failure_info = hazard_info['Event']['GroundFailure']
        if 'Liquefaction' in ground_failure_info.keys():
            trigging_info = ground_failure_info['Liquefaction']['Triggering']
            for key, item in trigging_info['Parameters'].items():
                if is_valid_path_format(item):
                    file_name = Path(item).name
                    new_path = os.path.join(input_dir, file_name)
                    trigging_info['Parameters'][key] = new_path
            hazard_info['Event']['GroundFailure']['Liquefaction']['Triggering'] = trigging_info
        if 'LateralSpreading' in ground_failure_info['Liquefaction'].keys():  # noqa: SIM118
            lat_spread_info = ground_failure_info['Liquefaction'][
                'LateralSpreading'
            ]
            for key, item in lat_spread_info['Parameters'].items():
                if is_valid_path_format(item):
                    file_name = Path(item).name
                    new_path = os.path.join(input_dir, file_name)
                    lat_spread_info['Parameters'][key] = new_path
            hazard_info['Event']['GroundFailure']['Liquefaction'][
                'LateralSpreading'
            ] = lat_spread_info
        if 'Settlement' in ground_failure_info['Liquefaction'].keys():  # noqa: SIM118
            settlement_info = ground_failure_info['Liquefaction']['Settlement']
            for key, item in settlement_info['Parameters'].items():
                if is_valid_path_format(item):
                    file_name = Path(item).name
                    new_path = os.path.join(input_dir, file_name)
                    settlement_info['Parameters'][key] = new_path
            hazard_info['Event']['GroundFailure']['Liquefaction'][
                'Settlement'
            ] = settlement_info
        if 'Landslide' in ground_failure_info.keys():
            if 'Landslide' in ground_failure_info['Landslide'].keys():  # noqa: SIM118
                lsld_info = ground_failure_info['Landslide']['Landslide']
                for key, item in lsld_info['Parameters'].items():
                    if is_valid_path_format(item):
                        file_name = Path(item).name
                        new_path = os.path.join(input_dir, file_name)
                        lsld_info['Parameters'][key] = new_path
                hazard_info['Event']['GroundFailure']['Landslide'][
                    'Landslide'
                ] = lsld_info
    # Save the hazard info
    with open(hazard_config_file, 'w') as f:
        json.dump(hazard_info, f, indent=2)
    # Get the scenarios to run
    print('HazardSimulation: loading scenarios.')  # noqa: T201
    scenario_info = hazard_info['Scenario']
    if scenario_info['Type'] == 'Earthquake':
        # KZ-10/31/2022: checking user-provided scenarios
        if scenario_info['EqRupture']['Type'] == 'oqSourceXML':
            print('HazardSimulation: currently only supports openSHA sources.')
            exit(1)
        else:
            rupFile = scenario_info['sourceFile']  # noqa: N806
            print('HazardSimulation: before load_earthquake_rupFile.')  # noqa: T201
            scenarios = load_earthquake_rupFile(scenario_info, rupFile)  # noqa: F405
    else:
        print('HazardSimulation: currently only supports EQ simulations.')
        exit(1)
    
    scenarios_to_run = list(scenarios.keys())
    # scenarios_to_run = [0] # for testing purposes
    print(f'HazardSimulation: scenarios_to_run:{scenarios_to_run}.')

    comm = MPI.COMM_WORLD
    numP = comm.Get_size()  # noqa: N806
    procID = comm.Get_rank()  # noqa: N806
    for sce_idx, sce_id in enumerate(scenarios_to_run):
        if sce_idx % numP == procID:
            command = f"{python_path} {calculation_single_process_file} --input_dir {input_dir} --sce_idx {sce_idx} --procID {procID}"
            print(f'HazardSimulation: command:{command}.')
            command = shlex.split(command)
            try:
                # result = subprocess.check_output(  # noqa: S603
                #     command, stderr=subprocess.PIPE, text=True
                # )

                # Start the subprocess
                process = subprocess.Popen(
                    command,  # Replace with your command and arguments
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True  # Automatically decode the output to text (Python 3.7+)
                )

                # Read stdout in real-time
                for line in process.stdout:
                    print(line, end='')  # Print each line as it's produced

                # Wait for the process to complete and get the return code
                process.wait()

                # Optionally, handle stderr
                stderr_output = process.stderr.read()
                if stderr_output:
                    print(f"Error: {stderr_output}")
                returncode = 0
            except subprocess.CalledProcessError as e:
                result = e.output
                returncode = e.returncode

            if returncode != 0:
                print(result)
                sys.exit(f'return code: {returncode}')
                


