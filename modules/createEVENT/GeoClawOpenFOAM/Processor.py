############################################################################
# This python routine forms the backend where all the files are generated
# to run the Hydro-UQ simulation
#############################################################################
import json
import datetime
import os
import shutil
import sys
import numpy as np
import argparse
import pip

# Import user-defined classes
from GenUtilities import genUtilities # General utilities
from OpenFOAM import solver # OpenFOAM class

####################################################################
def install(package):
    '''
    Install all the requirements.
    '''

    # Install all python libraries required
    # python3 -m pip3 install --user -r requirements.txt

    # if hasattr(pip, 'main'):
    #     pip.main(['install', package])
    # else:
    #     pip._internal.main(['install', package])

####################################################################
def main():
    '''
    This is the main routine which controls the flow of program.

    Objects:
        hydro_parser: Parse CLI arguments
        hydroutil: General utilities
        hydrosolver: Solver related file generation

    Variables:
        projname: Name of the project as given by the user
        logID: Integer ID for the log file
    '''

    # Get the system argument
    # Create the parser
    hydro_parser = argparse.ArgumentParser(description='Get the Dakota.json file')

    # Add the arguments
    hydro_parser.add_argument('-b',
                       metavar='path',
                       type=str,
                       help='the path to dakota.json file',
                       required=True)

    # Execute the parse_args() method
    args = hydro_parser.parse_args()

    # Open the JSON file
    # Load all the objects to the data variable
    # with open('dakota.json') as f:
    with open(args.b) as f:
        data = json.load(f)

    # Create the objects
    hydroutil = genUtilities() # General utilities
    hydrosolver = solver() # Solver object

    #***********************************
    # HYDRO-UQ LOG FILE: INITIALIZE
    #***********************************
    # Get the project name
    projname = hydroutil.extract_element_from_json(data, ["Events","ProjectName"])
    projname = ', '.join(projname)
    logID = 0

    # Initialize the log
    hydroutil.hydrolog(projname)

    # Start the log file with header and time and date
    logfiletext = hydroutil.general_header()
    hydroutil.flog.write(logfiletext)
    logID += 1
    hydroutil.flog.write('%d (%s): This log has started.\n' % (logID,datetime.datetime.now()))

    #***********************************
    # REQUIRED DIRECTORIES
    #***********************************
    # Create the OpenFOAM directories
    foldwrite = hydrosolver.dircreate()
    logID += 1
    hydroutil.flog.write('%d (%s): Following solver directories have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(foldwrite)))

    #***********************************
    # SUPPLEMENTARY SOLVER SPECIFIC FILES
    #***********************************
    fileswrite = hydrosolver.filecreate(data)
    logID += 1
    hydroutil.flog.write('%d (%s): Following required files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    #***********************************
    # MATERIAL MODEL RELATED FILES
    #***********************************
    fileswrite = hydrosolver.matmodel(data)
    logID += 1
    hydroutil.flog.write('%d (%s): Following material-related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    #***********************************
    # SIMULATION CONTROL RELATED FILES
    #***********************************
    fileswrite = hydrosolver.solvecontrol(data)
    logID += 1
    hydroutil.flog.write('%d (%s): Following solver-control related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    #***********************************
    # PARALLELIZATION CONTROL RELATED FILES
    #***********************************
    fileswrite = hydrosolver.parallel(data)
    logID += 1
    hydroutil.flog.write('%d (%s): Following parallel-compute related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    #***********************************
    # GEOMETRY RELATED FILES
    # Call this only if we are using Hydro mesher
    #***********************************
    mesher = hydroutil.extract_element_from_json(data, ["Events","MeshType"])
    if int(mesher[0]) == 0:
        fileswrite = hydrosolver.geometry(data)
        logID += 1
        hydroutil.flog.write('%d (%s): Following geometry-related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    else:
        hydroutil.flog.write('%d (%s): No geometric files have not been created since the user is providing the mesh\n' % (logID,datetime.datetime.now()))

    #***********************************
    # MESHING RELATED FILES
    #***********************************
    if int(mesher[0]) == 0:
        fileswrite = hydrosolver.meshing(data)
        logID += 1
        hydroutil.flog.write('%d (%s): Following meshing-related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    elif int(mesher[0]) == 2:

        fileswrite = np.array([])
        # Check if OF mesh dictionary exists then move to system
        if os.path.isfile("templateDir/blockMeshDict"):
            shutil.move("templateDir/blockMeshDict", "system/blockMeshDict")
            fileswrite = np.append(filewritten,['blockMeshDict'])

        if os.path.isfile("templateDir/surfaceFeatureExtractDict"):
            shutil.move("templateDir/surfaceFeatureExtractDict", "system/surfaceFeatureExtractDict")
            fileswrite = np.append(filewritten,['surfaceFeatureExtractDict'])

        if os.path.isfile("templateDir/snappyHexMeshDict"):
            shutil.move("templateDir/snappyHexMeshDict", "system/snappyHexMeshDict")
            fileswrite = np.append(filewritten,['snappyHexMeshDict'])
        
        if fileswrite.size != 0:
            # Confirm the copy
            hydroutil.flog.write('%d (%s): Following mesh dictionaries provided by the user have been copied to system folder: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

        else:
            hydroutil.flog.write('%d (%s): WARNING: Mesh dictionaries not found\n' % (logID,datetime.datetime.now()))

    else:
        hydroutil.flog.write('%d (%s): Mesh files are provided by the user and thus mesh-dictionary creation has been skipped\n' % (logID,datetime.datetime.now()))

    #***********************************
    # INITIAL CONDITIONS RELATED FILES
    # Presently only supports alpha
    #***********************************
    # fileswrite = hydrosolver.initcond(data)
    # logID += 1
    # hydroutil.flog.write('%d (%s): Following initial condition related files have been created: %s\n' % (logID,datetime.datetime.now(),', '.join(fileswrite)))

    #***********************************
    # BOUNDARY CONDITIONS RELATED FILES
    #***********************************

    #***********************************
    # RUNCASE SCRIPT FOR TACC
    #***********************************
    
    # Create the case run script
    fileIDrun = open("caserun.sh","w")

    # Start with meshing
    if int(mesher[0]) == 0:
        # Join all the STL files
        # Read the temporary geometry file with extreme values
        data_geoext = np.genfromtxt("temp_geometry", dtype=(float))
        flag = int(data_geoext[6])
        fileIDrun.write('echo Combining STL files for usage...\n')
        if flag == 0:
            fileIDrun.write('cat constant/triSurface/Front.stl constant/triSurface/Back.stl constant/triSurface/Top.stl constant/triSurface/Bottom.stl constant/triSurface/Left.stl constant/triSurface/Right.stl > constant/triSurface/Full.stl\n\n')
        elif flag == 1:
            fileIDrun.write('cat constant/triSurface/Front.stl constant/triSurface/Back.stl constant/triSurface/Top.stl constant/triSurface/Bottom.stl constant/triSurface/Left.stl constant/triSurface/Right.stl constant/triSurface/Building.stl > constant/triSurface/Full.stl\n\n')
        elif flag == 2:
            fileIDrun.write('cat constant/triSurface/Front.stl constant/triSurface/Back.stl constant/triSurface/Top.stl constant/triSurface/Bottom.stl constant/triSurface/Left.stl constant/triSurface/Right.stl constant/triSurface/Building.stl constant/triSurface/OtherBuilding.stl> constant/triSurface/Full.stl\n\n')

        # blockMesh
        fileIDrun.write('echo blockMesh running...\n')
        fileIDrun.write('blockMesh > blockMesh.log\n\n')
        # surfaceFeatureExtract
        fileIDrun.write('echo surfaceFeatureExtract running...\n')
        fileIDrun.write('surfaceFeatureExtract -force > sFeatureExt.log\n\n')
        # snappyHexMesh
        fileIDrun.write('echo snappyHexMesh running...\n')
        fileIDrun.write('snappyHexMesh > snappyHexMesh.log\n')
        # Copy the polyMesh folder
        fileIDrun.write('cp -r 2/polyMesh constant\n')
        # Remove folder 1 and 2
        fileIDrun.write('rm -fr 1 2\n')
        # Create new controlDict
        fileIDrun.write('python3 $HYDROBRAIN/ControlDict.py -b $BIM\n\n')

    
    elif int(mesher[0]) == 1:
        # blockMesh
        if os.path.isfile("templateDir/blockMeshDict"):
            fileIDrun.write('echo blockMesh running...\n')
            fileIDrun.write('blockMesh > blockMesh.log\n\n')
        # surfaceFeatureExtract
        if os.path.isfile("templateDir/surfaceFeatureExtractDict"):
            fileIDrun.write('echo surfaceFeatureExtract running...\n')
            fileIDrun.write('surfaceFeatureExtract -force > sFeatureExt.log\n\n')
        # snappyHexMesh
        if os.path.isfile("templateDir/snappyHexMeshDict"):
            fileIDrun.write('echo snappyHexMesh running...\n')
            fileIDrun.write('snappyHexMesh > snappyHexMesh.log\n')
            # Copy the polyMesh folder
            fileIDrun.write('cp -r 2/polyMesh constant\n')
            # Remove folder 1 and 2
            fileIDrun.write('rm -fr 1 2\n')
            # Create new controlDict
            fileIDrun.write('python3 $HYDROBRAIN/ControlDict.py -b $BIM\n\n')

    elif int(mesher[0]) == 2:
        # Get the mesh software
        meshsoftware = hydroutil.extract_element_from_json(data, ["Events","MeshSoftware"])
        # Get the mesh file name
        meshfile = hydroutil.extract_element_from_json(data, ["Events","MeshFile"])
        # Add the file paths
        fileIDrun.write('MESHFILE=${inputDirectory}/templatedir/'+meshfile[0]+'\n')
        # Write out the appropriate commands
        if int(meshsoftware[0]) == 0:
            fileIDrun.write('fluentMeshToFoam $MESHFILE > fluentMeshToFoam.log\n\n')
        elif int(meshsoftware[0]) == 1:
            fileIDrun.write('ideasToFoam $MESHFILE > ideasToFoam.log\n\n')
        elif int(meshsoftware[0]) == 2:
            fileIDrun.write('cfx4ToFoam $MESHFILE > cfx4ToFoam.log\n\n')
        elif int(meshsoftware[0]) == 3:
            fileIDrun.write('gambitToFoam $MESHFILE > gambitToFoam.log\n\n')
        elif int(meshsoftware[0]) == 4:
            fileIDrun.write('gmshToFoam $MESHFILE > gmshToFoam.log\n\n')

    # Check the mesh
    fileIDrun.write('echo Checking mesh...\n')
    fileIDrun.write('checkMesh > Meshcheck.log\n\n')

    # Create the 0-folder
    fileIDrun.write('echo Creating 0-folder...\n')
    fileIDrun.write('rm -fr 0\n')
    fileIDrun.write('cp -r 0.org 0\n\n')

    # Setting the fields
    fileIDrun.write('echo Setting fields...\n')
    fileIDrun.write('setFields > setFields.log\n\n')

    # Decompose the domain
    fileIDrun.write('echo Decomposing domain...\n')
    fileIDrun.write('decomposePar > decomposePar.log\n\n')

    # Start the CFD simulation
    # Get the number of processors required
    procs = ', '.join(hydroutil.extract_element_from_json(data, ["Events","DomainDecomposition"]))
    procs = procs.replace(',', ' ')
    nums = [int(n) for n in procs.split()]
    totalprocs = nums[0]*nums[1]*nums[2]
    fileIDrun.write('echo Starting CFD simulation...\n')
    fileIDrun.write('mpirun -np '+str(totalprocs)+' olaDyMFlow -parallel > olaDyMFlow.log\n\n')

    # Call building forces to run Dakota
    fileIDrun.write('echo Starting Dakota preparation...\n')
    fileIDrun.write('python3 $HYDROBRAIN/GetOpenFOAMEvent.py -b $BIM\n')
    fileIDrun.write('cp -f EVENT.json ${inputDirectory}/templatedir/EVENT.json\n')
    fileIDrun.write('cp -f EVENT.json ${inputDirectory}/templatedir/evt.j\n\n')

    # Load necessary modules
    fileIDrun.write('echo Loading necessary modules for Dakota...\n')
    fileIDrun.write('module load intel/18.0.2  impi/18.0.2 dakota/6.8.0 python3\n\n')
    
    # Initialize file names and scripts
    fileIDrun.write('echo Initializing file names and scripts...\n')
    fileIDrun.write('echo "inputScript is ${inputFile}"\n')
    fileIDrun.write('INPUTFILE=\'${inputFile}\'\n')
    fileIDrun.write('INPUTFILE="${INPUTFILE##*/}"\n')
    fileIDrun.write('echo "driver is ${driverFile}"\n')
    fileIDrun.write('DRIVERFILE=\'${driverFile}\'\n')
    fileIDrun.write('DRIVERFILE="${DRIVERFILE##*/}"\n')
    fileIDrun.write('Change script permissions...\n')
    fileIDrun.write('cd templatedir\n')
    fileIDrun.write('chmod \'a+x\' $DRIVERFILE\n')
    fileIDrun.write('chmod \'a+x\' dpreproSimCenter\n')
    fileIDrun.write('cp $DRIVERFILE ../\n')
    fileIDrun.write('cd..\n\n')

    # Run Dakota
    fileIDrun.write('echo Running dakota...\n')
    fileIDrun.write('ibrun dakota -in $INPUTFILE -out dakota.out -err dakota.err\n\n')

    # Clean up all the directories
    fileIDrun.write('echo Cleaning up...\n')
    fileIDrun.write('cp templatedir/dakota.json ./\n')
    fileIDrun.write('rm -fr templatedir\n')
    fileIDrun.write('rm temp_geometry\n\n')

####################################################################
if __name__ == "__main__":
    
    # Install the requirements
    # install('requirements.txt')
    
    # Call the main routine
    main()
