"""
This script writes BC and initial condition, and setups the OpenFoam case 
directory.

"""
import numpy as np
import sys
import os
import json
import numpy as np
import foam_file_processor as foam
from stl import mesh


def write_block_mesh_dict(input_json_path, template_dict_path, case_path):

    #Read JSON data    
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)
      
    # Returns JSON object as a dictionary
    mesh_data = json_data["blockMeshParameters"]
    geom_data = json_data['GeometricData']
    boundary_data = json_data["boundaryConditions"]    

    origin = np.array(geom_data['origin'])
    scale =  geom_data['geometricScale']
    
    Lx = geom_data['domainLength']
    Ly = geom_data['domainWidth']
    Lz = geom_data['domainHeight']
    Lf = geom_data['fetchLength']
    
    x_cells = mesh_data['xNumCells']
    y_cells = mesh_data['yNumCells']
    z_cells = mesh_data['zNumCells']
    
    x_grading = mesh_data['xGrading']
    y_grading = mesh_data['yGrading']
    z_grading = mesh_data['zGrading']


    bc_map = {"slip": 'wall', "cyclic": 'cyclic', "noSlip": 'wall', 
                     "symmetry": 'symmetry', "empty": 'empty', "TInf": 'patch', 
                     "MeanABL": 'patch', "Uniform": 'patch', "zeroPressureOutlet": 'patch',
                     "roughWallFunction": 'wall',"smoothWallFunction": 'wall'}

    inlet_type = bc_map[boundary_data['inletBoundaryCondition']]
    outlet_type = bc_map[boundary_data['outletBoundaryCondition']]
    ground_type = bc_map[boundary_data['groundBoundaryCondition']]  
    top_type = bc_map[boundary_data['topBoundaryCondition']]
    front_type = bc_map[boundary_data['sidesBoundaryCondition']]
    back_type = bc_map[boundary_data['sidesBoundaryCondition']]

    length_unit = json_data['lengthUnit']

    
    x_min = -Lf - origin[0]
    y_min = -Ly/2.0 - origin[1]
    z_min =  0.0 - origin[2]

    x_max = x_min + Lx
    y_max = y_min + Ly
    z_max = z_min + Lz

    #Open the template blockMeshDict (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/blockMeshDictTemplate", "r")

    #Export to OpenFOAM probe format
    dict_lines = dict_file.readlines()
    dict_file.close()
    

    dict_lines[17] = "\txMin\t\t{:.4f};\n".format(x_min)
    dict_lines[18] = "\tyMin\t\t{:.4f};\n".format(y_min)
    dict_lines[19] = "\tzMin\t\t{:.4f};\n".format(z_min)

    dict_lines[20] = "\txMax\t\t{:.4f};\n".format(x_max)
    dict_lines[21] = "\tyMax\t\t{:.4f};\n".format(y_max)
    dict_lines[22] = "\tzMax\t\t{:.4f};\n".format(z_max)


    dict_lines[23] = "\txCells\t\t{:d};\n".format(x_cells)
    dict_lines[24] = "\tyCells\t\t{:d};\n".format(y_cells)
    dict_lines[25] = "\tzCells\t\t{:d};\n".format(z_cells)

    dict_lines[26] = "\txGrading\t{:.4f};\n".format(x_grading)
    dict_lines[27] = "\tyGrading\t{:.4f};\n".format(y_grading)
    dict_lines[28] = "\tzGrading\t{:.4f};\n".format(z_grading)

    convert_to_meters = 1.0

    if length_unit=='m':
        convert_to_meters = 1.0
    elif length_unit=='cm':
        convert_to_meters = 0.01
    elif length_unit=='mm':
        convert_to_meters = 0.001
    elif length_unit=='ft':
        convert_to_meters = 0.3048
    elif length_unit=='in':
        convert_to_meters = 0.0254

    dict_lines[31] = "convertToMeters {:.4f};\n".format(convert_to_meters)
    dict_lines[61] = "        type {};\n".format(inlet_type)
    dict_lines[70] = "        type {};\n".format(outlet_type)
    dict_lines[79] = "        type {};\n".format(ground_type)
    dict_lines[88] = "        type {};\n".format(top_type)
    dict_lines[97] = "        type {};\n".format(front_type)
    dict_lines[106] = "        type {};\n".format(back_type)

    
    write_file_name = case_path + "/system/blockMeshDict"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()



def write_snappy_hex_mesh_dict(input_json_path, template_dict_path, case_path):

    #Read JSON data    
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)
      
    # Returns JSON object as a dictionary
    mesh_data = json_data["snappyHexMeshParameters"]

    geom_data = json_data['GeometricData']
   
    Lx = geom_data['domainLength']
    Ly = geom_data['domainWidth']
    Lz = geom_data['domainHeight']
    Lf = geom_data['fetchLength']
    
    origin = np.array(geom_data['origin'])
    
    num_cells_between_levels = mesh_data['numCellsBetweenLevels']
    resolve_feature_angle = mesh_data['resolveFeatureAngle']
    num_processors = mesh_data['numProcessors']
    
    refinement_boxes = mesh_data['refinementBoxes']
    
    x_min = -Lf - origin[0]
    y_min = -Ly/2.0 - origin[1]
    z_min =  0.0 - origin[2]

    x_max = x_min + Lx
    y_max = y_min + Ly
    z_max = z_min + Lz    
    
    inside_point  = [x_min + Lf/2.0, (y_min + y_max)/2.0, (z_min + z_max)/2.0]


    #Open the template blockMeshDict (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/snappyHexMeshDictTemplate", "r")

    #Export to OpenFOAM probe format
    dict_lines = dict_file.readlines()
    dict_file.close()
    
    
    #Write 'addLayers' switch    
    start_index = foam.find_keyword_line(dict_lines, "addLayers")
    dict_lines[start_index] = "addLayers\t{};\n".format("off")
    
    ###################### Edit Geometry Section ##############################
    
    #Add refinement box geometry
    start_index = foam.find_keyword_line(dict_lines, "geometry") + 2 
    added_part = ""
    n_boxes  = len(refinement_boxes)
    for i in range(n_boxes):
        added_part += "    {}\n".format(refinement_boxes[i][0])
        added_part += "    {\n"
        added_part += "         type searchableBox;\n"
        added_part += "         min ({:.4f} {:.4f} {:.4f});\n".format(refinement_boxes[i][2], refinement_boxes[i][3], refinement_boxes[i][4])
        added_part += "         max ({:.4f} {:.4f} {:.4f});\n".format(refinement_boxes[i][5], refinement_boxes[i][6], refinement_boxes[i][7])
        added_part += "    }\n"
        
    dict_lines.insert(start_index, added_part)
           
    
    ################# Edit castellatedMeshControls Section ####################

    #Write 'nCellsBetweenLevels'     
    start_index = foam.find_keyword_line(dict_lines, "nCellsBetweenLevels")
    dict_lines[start_index] = "    nCellsBetweenLevels {:d};\n".format(num_cells_between_levels)

    #Write 'resolveFeatureAngle'     
    start_index = foam.find_keyword_line(dict_lines, "resolveFeatureAngle")
    dict_lines[start_index] = "    resolveFeatureAngle {:d};\n".format(resolve_feature_angle)

    #Write 'insidePoint'     
    start_index = foam.find_keyword_line(dict_lines, "insidePoint")
    dict_lines[start_index] = "    insidePoint ({:.4f} {:.4f} {:.4f});\n".format(inside_point[0], inside_point[1], inside_point[2])

    #For compatibility with OpenFOAM-9 and older
    start_index = foam.find_keyword_line(dict_lines, "locationInMesh")
    dict_lines[start_index] = "    locationInMesh ({:.4f} {:.4f} {:.4f});\n".format(inside_point[0], inside_point[1], inside_point[2])

    #Write 'outsidePoint' on Frontera snappyHex will fail without this keyword    
    start_index = foam.find_keyword_line(dict_lines, "outsidePoint")
    dict_lines[start_index] = "    outsidePoint ({:.4e} {:.4e} {:.4e});\n".format(-1e-20, -1e-20, -1e-20)


    
    #Add box refinements 
    added_part = ""
    for i in range(n_boxes):
        added_part += "         {}\n".format(refinement_boxes[i][0])
        added_part += "         {\n"
        added_part += "             mode   inside;\n"
        added_part += "             level  {};\n".format(refinement_boxes[i][1])
        added_part += "         }\n"
                
    start_index = foam.find_keyword_line(dict_lines, "refinementRegions") + 2 
    dict_lines.insert(start_index, added_part)
       
    
    #Write edited dict to file
    write_file_name = case_path + "/system/snappyHexMeshDict"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()


def write_boundary_data_files(input_json_path, case_path):
    """
    This functions writes wind profile files in "constant/boundaryData/inlet"
    if TInf options are used for the simulation.  
    """
    #Read JSON data    
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]    

    if boundary_data['inletBoundaryCondition']=="TInf":
        geom_data = json_data['GeometricData']

        wind_profiles =  np.array(boundary_data["inflowProperties"]['windProfiles'])

        bd_path = case_path + "/constant/boundaryData/inlet/"

        #Write points file
        n_pts = np.shape(wind_profiles)[0]
        points  = np.zeros((n_pts, 3))


        origin = np.array(geom_data['origin'])
        
        Ly = geom_data['domainWidth']
        Lf = geom_data['fetchLength']
        
        x_min = -Lf - origin[0]
        y_min = -Ly/2.0 - origin[1]
        y_max = y_min + Ly

        points[:,0] = x_min
        points[:,1] = (y_min + y_max)/2.0  
        points[:,2] = wind_profiles[:, 0]

        #Shift the last element of the y coordinate 
        #a bit to make planer interpolation easier
        points[-1:, 1] = y_max

        foam.write_foam_field(points, bd_path + "points")

        #Write wind speed file as a scalar field 
        foam.write_scalar_field(wind_profiles[:, 1], bd_path + "U")

        #Write Reynolds stress profile (6 columns -> it's a symmetric tensor field) 
        foam.write_foam_field(wind_profiles[:, 2:8], bd_path + "R")

        #Write length scale file (8 columns -> it's a tensor field)
        foam.write_foam_field(wind_profiles[:, 8:17], bd_path + "L")


def write_U_file(input_json_path, template_dict_path, case_path):

    #Read JSON data    
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]    
    wind_data = json_data["windCharacteristics"]
    
      
    inlet_BC_type =  boundary_data['inletBoundaryCondition']
    top_BC_type = boundary_data['topBoundaryCondition']
    sides_BC_type = boundary_data['sidesBoundaryCondition']
 
    wind_speed = wind_data['referenceWindSpeed']
    building_height = wind_data['referenceHeight']
    roughness_length = wind_data['aerodynamicRoughnessLength']


    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/UFileTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    ##################### Internal Field #########################
    #Initialize the internal fields frow a lower velocity to avoid Courant number 
    #instability when the solver starts. Now %10 of roof-height wind speed is set      
    start_index = foam.find_keyword_line(dict_lines, "internalField") 
    # dict_lines[start_index] = "internalField   uniform ({:.4f} 0 0);\n".format(1.0*wind_speed)

    #Set the internal field to zero to make it easy for the solver to start
    dict_lines[start_index] = "internalField   uniform (0 0 0);\n"


    ###################### Inlet BC ##############################  
    #Write uniform
    start_index = foam.find_keyword_line(dict_lines, "inlet") + 2 

    if inlet_BC_type == "Uniform":    
        added_part = ""
        added_part += "\t type \t fixedValue;\n"
        added_part += "\t value \t uniform ({:.4f} 0 0);\n".format(wind_speed)
        
    if inlet_BC_type == "MeanABL":    
        added_part = ""
        added_part += "\t type \t atmBoundaryLayerInletVelocity;\n"
        added_part += "\t Uref \t {:.4f};\n".format(wind_speed)
        added_part += "\t Zref \t {:.4f};\n".format(building_height)
        added_part += "\t zDir \t (0.0 0.0 1.0);\n"
        added_part += "\t flowDir \t (1.0 0.0 0.0);\n"
        added_part += "\t z0 uniform \t {:.4e};\n".format(roughness_length)
        added_part += "\t zGround \t uniform 0.0;\n"
        
    if inlet_BC_type == "TInf":    
        added_part = ""
        added_part += "\t type \t turbulentDFMInlet;\n"
        added_part += "\t filterType \t exponential;\n"
        added_part += "\t filterFactor \t {};\n".format(4)
        added_part += "\t value \t uniform ({:.4f} 0 0);\n".format(wind_speed)
        added_part += "\t periodicInY \t {};\n".format("true")
        added_part += "\t periodicInZ \t {};\n".format("false")
        added_part += "\t constMeanU \t {};\n".format("true")
        added_part += "\t Uref \t {:.4f};\n".format(wind_speed)

    dict_lines.insert(start_index, added_part)

    ###################### Outlet BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "outlet") + 2 
    added_part = ""
    added_part += "\t type \t inletOutlet;\n"
    added_part += "\t inletValue \t uniform (0 0 0);\n"
    added_part += "\t value \t uniform (0 0 0);\n"

    dict_lines.insert(start_index, added_part)
    
    ###################### Ground BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "ground") + 2 
    added_part = ""
    added_part += "\t type \t uniformFixedValue;\n"
    added_part += "\t value \t uniform (0 0 0);\n"
    added_part += "\t uniformValue \t constant (0 0 0);\n"
    
    dict_lines.insert(start_index, added_part)
    
    
    ###################### Top BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "top") + 2 
    added_part = ""
    added_part += "\t type    {};\n".format(top_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Front BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "front") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Back BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "back") + 2 
    added_part = ""
    added_part += "\t type    {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)

    
    #Write edited dict to file
    write_file_name = case_path + "/0/U"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    

def write_p_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]
      
    sides_BC_type = boundary_data['sidesBoundaryCondition']
    top_BC_type = boundary_data['topBoundaryCondition']


    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/pFileTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    
    #BC and initial condition
    p0 = 0.0; 


    ##################### Internal Field #########################
    
    start_index = foam.find_keyword_line(dict_lines, "internalField") 
    dict_lines[start_index] = "internalField   uniform {:.4f};\n".format(p0)


    ###################### Inlet BC ##############################  
    #Write uniform
    start_index = foam.find_keyword_line(dict_lines, "inlet") + 2 
    added_part = ""
    added_part += "\t type \t zeroGradient;\n"
    
    dict_lines.insert(start_index, added_part)

    ###################### Outlet BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "outlet") + 2 
    added_part = ""
    added_part += "\t type \t  uniformFixedValue;\n"
    added_part += "\t uniformValue \t constant {:.4f};\n".format(p0)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Ground BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "ground") + 2 
    added_part = ""
    added_part += "\t type \t zeroGradient;\n"
    
    dict_lines.insert(start_index, added_part)
    
    
    ###################### Top BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "top") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(top_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Front BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "front") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Back BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "back") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    
    #Write edited dict to file
    write_file_name = case_path + "/0/p"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    
def write_nut_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]
    wind_data = json_data["windCharacteristics"]
          
    sides_BC_type = boundary_data['sidesBoundaryCondition']
    top_BC_type = boundary_data['topBoundaryCondition']
    ground_BC_type = boundary_data['groundBoundaryCondition']


    # wind_speed = wind_data['roofHeightWindSpeed']
    # building_height = wind_data['buildingHeight']
    roughness_length = wind_data['aerodynamicRoughnessLength']
    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/nutFileTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    
    #BC and initial condition
    nut0 = 0.0 

    ##################### Internal Field #########################
    
    start_index = foam.find_keyword_line(dict_lines, "internalField") 
    dict_lines[start_index] = "internalField   uniform {:.4f};\n".format(nut0)


    ###################### Inlet BC ##############################  
    #Write uniform
    start_index = foam.find_keyword_line(dict_lines, "inlet") + 2 
    added_part  = ""
    added_part += "\t type \t zeroGradient;\n"
    
    dict_lines.insert(start_index, added_part)

    ###################### Outlet BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "outlet") + 2 
    added_part = ""
    added_part += "\t type \t uniformFixedValue;\n"
    added_part += "\t uniformValue \t constant {:.4f};\n".format(nut0)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Ground BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "ground") + 2 
    
    if ground_BC_type == "noSlip": 
        added_part = ""
        added_part += "\t type \t zeroGradient;\n"
    
    if ground_BC_type == "roughWallFunction": 
        added_part = ""
        added_part += "\t type \t nutkAtmRoughWallFunction;\n"
        added_part += "\t z0  \t  uniform {:.4e};\n".format(roughness_length)
        added_part += "\t value \t uniform 0.0;\n"

    if ground_BC_type == "smoothWallFunction": 
        added_part = ""
        added_part += "\t type \t nutUSpaldingWallFunction;\n"
        added_part += "\t value \t uniform 0;\n"


    dict_lines.insert(start_index, added_part)
    
    
    ###################### Top BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "top") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(top_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Front BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "front") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Back BC ################################  
    
    start_index = foam.find_keyword_line(dict_lines, "back") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    
    #Write edited dict to file
    write_file_name = case_path + "/0/nut"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()

def write_epsilon_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]
    wind_data = json_data["windCharacteristics"]
      
    
    sides_BC_type = boundary_data['sidesBoundaryCondition']
    top_BC_type = boundary_data['topBoundaryCondition']
    ground_BC_type = boundary_data['groundBoundaryCondition']

    wind_speed = wind_data['referenceWindSpeed']
    building_height = wind_data['referenceHeight']
    roughness_length = wind_data['aerodynamicRoughnessLength']
    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/epsilonFileTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    
    #BC and initial condition
    epsilon0 = 0.01 

    ##################### Internal Field #########################
    
    start_index = foam.find_keyword_line(dict_lines, "internalField") 
    dict_lines[start_index] = "internalField   uniform {:.4f};\n".format(epsilon0)


    ###################### Inlet BC ##############################  
    #Write uniform
    start_index = foam.find_keyword_line(dict_lines, "inlet") + 2 
    added_part  = ""
    added_part += "\t type \t atmBoundaryLayerInletEpsilon;\n"
    added_part += "\t Uref \t {:.4f};\n".format(wind_speed)
    added_part += "\t Zref \t {:.4f};\n".format(building_height)
    added_part += "\t zDir \t (0.0 0.0 1.0);\n"
    added_part += "\t flowDir \t (1.0 0.0 0.0);\n"
    added_part += "\t z0 \t  uniform {:.4e};\n".format(roughness_length)
    added_part += "\t zGround \t uniform 0.0;\n"
    
    dict_lines.insert(start_index, added_part)

    ###################### Outlet BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "outlet") + 2 
    added_part = ""
    added_part += "\t type \t inletOutlet;\n"
    added_part += "\t inletValue \t uniform {:.4f};\n".format(epsilon0)
    added_part += "\t value \t uniform {:.4f};\n".format(epsilon0)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Ground BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "ground") + 2 
    
    if ground_BC_type == "noSlip": 
        added_part = ""
        added_part += "\t type \t zeroGradient;\n"
    
    if ground_BC_type == "roughWallFunction": 
        added_part = ""
        added_part += "\t type \t epsilonWallFunction;\n"
        added_part += "\t Cmu \t {:.4f};\n".format(0.09)
        added_part += "\t kappa \t {:.4f};\n".format(0.41)
        added_part += "\t E \t {:.4f};\n".format(9.8)
        added_part += "\t value \t uniform {:.4f};\n".format(epsilon0)
    
    #Note:  Should be replaced with smooth wall function for epsilon,
    #       now the same with rough wall function.
    if ground_BC_type == "smoothWallFunction": 
        added_part = ""
        added_part += "\t type \t epsilonWallFunction;\n"
        added_part += "\t Cmu \t {:.4f};\n".format(0.09)
        added_part += "\t kappa \t {:.4f};\n".format(0.41)
        added_part += "\t E \t {:.4f};\n".format(9.8)
        added_part += "\t value \t uniform {:.4f};\n".format(epsilon0)
    dict_lines.insert(start_index, added_part)
    
    
    ###################### Top BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "top") + 2 
    added_part = ""
    added_part += "\t type  \t  {};\n".format(top_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Front BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "front") + 2 
    added_part = ""
    added_part += "\t type  \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Back BC ################################  
    
    start_index = foam.find_keyword_line(dict_lines, "back") + 2 
    added_part = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    #Write edited dict to file
    write_file_name = case_path + "/0/epsilon"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()

def write_k_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    boundary_data = json_data["boundaryConditions"]
    wind_data = json_data["windCharacteristics"]
      
    
    sides_BC_type = boundary_data['sidesBoundaryCondition']
    top_BC_type = boundary_data['topBoundaryCondition']
    ground_BC_type = boundary_data['groundBoundaryCondition']

    wind_speed = wind_data['referenceWindSpeed']
    building_height = wind_data['referenceHeight']
    roughness_length = wind_data['aerodynamicRoughnessLength']
    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/kFileTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    
    #BC and initial condition (you may need to scale to model scale)
    # k0 = 1.3 #not in model scale
    
    I = 0.1 
    k0 = 1.5*(I*wind_speed)**2  

    ##################### Internal Field #########################
    
    start_index = foam.find_keyword_line(dict_lines, "internalField") 
    dict_lines[start_index] = "internalField \t uniform {:.4f};\n".format(k0)


    ###################### Inlet BC ##############################  
    #Write uniform
    start_index = foam.find_keyword_line(dict_lines, "inlet") + 2 
    added_part  = ""
    added_part += "\t type \t atmBoundaryLayerInletK;\n"
    added_part += "\t Uref \t {:.4f};\n".format(wind_speed)
    added_part += "\t Zref \t {:.4f};\n".format(building_height)
    added_part += "\t zDir \t (0.0 0.0 1.0);\n"
    added_part += "\t flowDir \t (1.0 0.0 0.0);\n"
    added_part += "\t z0 \t uniform {:.4e};\n".format(roughness_length)
    added_part += "\t zGround \t uniform 0.0;\n"
    
    dict_lines.insert(start_index, added_part)

    ###################### Outlet BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "outlet") + 2 
    added_part = ""
    added_part += "\t type \t inletOutlet;\n"
    added_part += "\t inletValue \t uniform {:.4f};\n".format(k0)
    added_part += "\t value \t uniform {:.4f};\n".format(k0)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Ground BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "ground") + 2 
    
    if ground_BC_type == "noSlip": 
        added_part = ""
        added_part += "\t type \t zeroGradient;\n"
    
    if ground_BC_type == "smoothWallFunction": 
        added_part = ""
        added_part += "\t type \t kqRWallFunction;\n"
        added_part += "\t value \t uniform {:.4f};\n".format(0.0)

    if ground_BC_type == "roughWallFunction": 
        added_part = ""
        added_part += "\t type \t kqRWallFunction;\n"
        added_part += "\t value \t uniform {:.4f};\n".format(0.0)

    dict_lines.insert(start_index, added_part)
    
    
    ###################### Top BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "top") + 2 
    added_part = ""
    added_part += "\t type  \t {};\n".format(top_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Front BC ##############################  
    
    start_index = foam.find_keyword_line(dict_lines, "front") + 2 
    added_part  = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    ###################### Back BC ################################  
    
    start_index = foam.find_keyword_line(dict_lines, "back") + 2 
    added_part  = ""
    added_part += "\t type \t {};\n".format(sides_BC_type)
    
    dict_lines.insert(start_index, added_part)
    
    #Write edited dict to file
    write_file_name = case_path + "/0/k"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    
    
def write_controlDict_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    ns_data = json_data["numericalSetup"]
    rm_data = json_data["resultMonitoring"]
          
    solver_type = ns_data['solverType']
    duration = ns_data['duration']
    time_step = ns_data['timeStep']
    max_courant_number = ns_data['maxCourantNumber']
    adjust_time_step = ns_data['adjustTimeStep']
    
    monitor_wind_profiles = rm_data['monitorWindProfile']
    monitor_vtk_planes = rm_data['monitorVTKPlane']
    wind_profiles = rm_data['windProfiles']
    vtk_planes = rm_data['vtkPlanes']

    
    # Need to change this for      
    max_delta_t = 10*time_step
    
    #Write 10 times
    write_frequency = 10.0
    write_interval_time = duration/write_frequency 
    write_interval_count = int(write_interval_time/time_step)
    purge_write =  3
    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/controlDictTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    #Write application type 
    start_index = foam.find_keyword_line(dict_lines, "application") 
    dict_lines[start_index] = "application \t{};\n".format(solver_type)
    
    #Write end time 
    start_index = foam.find_keyword_line(dict_lines, "endTime") 
    dict_lines[start_index] = "endTime \t{:.6f};\n".format(duration)
    
    #Write time step time 
    start_index = foam.find_keyword_line(dict_lines, "deltaT") 
    dict_lines[start_index] = "deltaT \t\t{:.6f};\n".format(time_step)

    #Write writeControl         
    start_index = foam.find_keyword_line(dict_lines, "writeControl") 
    if solver_type=="pimpleFoam" and adjust_time_step:
        dict_lines[start_index] = "writeControl \t{};\n".format("adjustableRunTime")
    else:
        dict_lines[start_index] = "writeControl \t\t{};\n".format("timeStep")
    
    #Write adjustable time step or not  
    start_index = foam.find_keyword_line(dict_lines, "adjustTimeStep") 
    dict_lines[start_index] = "adjustTimeStep \t\t{};\n".format("yes" if adjust_time_step else "no")
 
    #Write writeInterval  
    start_index = foam.find_keyword_line(dict_lines, "writeInterval")     
    if solver_type=="pimpleFoam" and adjust_time_step:
        dict_lines[start_index] = "writeInterval \t{:.6f};\n".format(write_interval_time)
    else:
        dict_lines[start_index] = "writeInterval \t{};\n".format(write_interval_count)

    #Write maxCo  
    start_index = foam.find_keyword_line(dict_lines, "maxCo") 
    dict_lines[start_index] = "maxCo \t{:.2f};\n".format(max_courant_number)
    
    #Write maximum time step  
    start_index = foam.find_keyword_line(dict_lines, "maxDeltaT") 
    dict_lines[start_index] = "maxDeltaT \t{:.6f};\n".format(max_delta_t)
       

    #Write purge write interval  
    start_index = foam.find_keyword_line(dict_lines, "purgeWrite") 
    dict_lines[start_index] = "purgeWrite \t{};\n".format(purge_write)

    ########################### Function Objects ##############################
     
    #Find function object location  
    start_index = foam.find_keyword_line(dict_lines, "functions") + 2

    #Write wind profile monitoring functionObjects
    if monitor_wind_profiles:
        added_part = ""
        for prof in wind_profiles:
            added_part += "    #includeFunc  {}\n".format(prof["name"])
        dict_lines.insert(start_index, added_part)
    
    #Write VTK sampling sampling points 
    if monitor_vtk_planes:
        added_part = ""
        for pln in vtk_planes:
            added_part += "    #includeFunc  {}\n".format(pln["name"])
        dict_lines.insert(start_index, added_part)
    

    #Write edited dict to file
    write_file_name = case_path + "/system/controlDict"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    
def write_fvSolution_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    ns_data = json_data["numericalSetup"]
      
    json_file.close()
    
    num_non_orthogonal_correctors = ns_data['numNonOrthogonalCorrectors']
    num_correctors = ns_data['numCorrectors']
    num_outer_correctors = ns_data['numOuterCorrectors']
        
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/fvSolutionTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()

    
    #Write simpleFoam options  
    start_index = foam.find_keyword_line(dict_lines, "SIMPLE") + 2   
    added_part = ""
    added_part += "    nNonOrthogonalCorrectors \t{};\n".format(num_non_orthogonal_correctors)
    dict_lines.insert(start_index, added_part)

    
    #Write pimpleFoam options  
    start_index = foam.find_keyword_line(dict_lines, "PIMPLE") + 2   
    added_part = ""
    added_part += "    nOuterCorrectors \t{};\n".format(num_outer_correctors)
    added_part += "    nCorrectors \t{};\n".format(num_correctors)
    added_part += "    nNonOrthogonalCorrectors \t{};\n".format(num_non_orthogonal_correctors)
    dict_lines.insert(start_index, added_part)


    #Write pisoFoam options  
    start_index = foam.find_keyword_line(dict_lines, "PISO") + 2   
    added_part = ""
    added_part += "    nCorrectors \t{};\n".format(num_correctors)
    added_part += "    nNonOrthogonalCorrectors \t{};\n".format(num_non_orthogonal_correctors)
    dict_lines.insert(start_index, added_part)
   
   
    #Write edited dict to file
    write_file_name = case_path + "/system/fvSolution"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()    


def write_pressure_probes_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data = json.load(json_file)

    # Returns JSON object as a dictionary
    rm_data = json_data["resultMonitoring"]

    pressure_sampling_points = rm_data['pressureSamplingPoints']
    pressure_write_interval = rm_data['pressureWriteInterval']

    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/probeTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    

    #Write writeInterval 
    start_index = foam.find_keyword_line(dict_lines, "writeInterval") 
    dict_lines[start_index] = "writeInterval \t{};\n".format(pressure_write_interval)
        
    #Write fields to be motored 
    start_index = foam.find_keyword_line(dict_lines, "fields") 
    dict_lines[start_index] = "fields \t\t(p);\n"
    
    start_index = foam.find_keyword_line(dict_lines, "probeLocations") + 2

    added_part = ""
    
    for i in range(len(pressure_sampling_points)):
        added_part += " ({:.6f} {:.6f} {:.6f})\n".format(pressure_sampling_points[i][0], pressure_sampling_points[i][1], pressure_sampling_points[i][2])
    
    dict_lines.insert(start_index, added_part)

    #Write edited dict to file
    write_file_name = case_path + "/system/pressureSamplingPoints"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    
    
  
def write_wind_profiles_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    rm_data = json_data["resultMonitoring"]   

    ns_data = json_data["numericalSetup"]
    solver_type = ns_data['solverType']
    time_step = ns_data['timeStep']

    wind_profiles = rm_data['windProfiles']
    write_interval = rm_data['profileWriteInterval']
    start_time = rm_data['profileStartTime']

    if rm_data['monitorWindProfile'] == False:
        return 
    
    if len(wind_profiles)==0: 
        return

    #Write dict files for wind profiles
    for prof in wind_profiles:
        #Open the template file (OpenFOAM file) for manipulation
        dict_file = open(template_dict_path + "/probeTemplate", "r")

        dict_lines = dict_file.readlines()
        dict_file.close()
        
        #Write writeControl 
        start_index = foam.find_keyword_line(dict_lines, "writeControl") 
        if solver_type=="pimpleFoam":
            dict_lines[start_index] = "    writeControl \t{};\n".format("adjustableRunTime")
        else:
            dict_lines[start_index] = "    writeControl \t{};\n".format("timeStep")  

        #Write writeInterval
        start_index = foam.find_keyword_line(dict_lines, "writeInterval")     
        if solver_type=="pimpleFoam":
            dict_lines[start_index] = "    writeInterval \t{:.6f};\n".format(write_interval*time_step)
        else:
            dict_lines[start_index] = "    writeInterval \t{};\n".format(write_interval)

        #Write start time for the probes  
        start_index = foam.find_keyword_line(dict_lines, "timeStart") 
        dict_lines[start_index] = "    timeStart \t\t{:.6f};\n".format(start_time)   

        #Write name of the profile 
        name = prof["name"]
        start_index = foam.find_keyword_line(dict_lines, "profileName") 
        dict_lines[start_index] = "{}\n".format(name) 

        #Write field type 
        field_type = prof["field"]
        start_index = foam.find_keyword_line(dict_lines, "fields") 

        if field_type=="Velocity":
            dict_lines[start_index] = "  fields \t\t({});\n".format("U")
        if field_type=="Pressure":
            dict_lines[start_index] = "  fields \t\t({});\n".format("p")

        #Write point coordinates
        start_x = prof["startX"]
        start_y = prof["startY"]
        start_z = prof["startZ"]

        end_x = prof["endX"]
        end_y = prof["endY"]
        end_z = prof["endZ"]
        n_points = prof["nPoints"]

        dx = (end_x - start_x)/n_points
        dy = (end_y - start_y)/n_points
        dz = (end_z - start_z)/n_points

        #Write locations of the probes
        start_index = foam.find_keyword_line(dict_lines, "probeLocations") + 2 
        added_part = ""
        
        for pi in range(n_points): 
            added_part += "    ({:.6f} {:.6f} {:.6f})\n".format(start_x + pi*dx, start_y + pi*dy, start_z + pi*dz)
            
        dict_lines.insert(start_index, added_part)       

        #Write edited dict to file
        write_file_name = case_path + "/system/" + name
        
        if os.path.exists(write_file_name):
            os.remove(write_file_name)
        
        output_file = open(write_file_name, "w+")
        for line in dict_lines:
            output_file.write(line)
        output_file.close()
    
def write_vtk_plane_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    rm_data = json_data["resultMonitoring"]   
    ns_data = json_data["numericalSetup"]
    solver_type = ns_data['solverType']
    time_step = ns_data['timeStep']


    vtk_planes = rm_data['vtkPlanes']
    write_interval = rm_data['vtkWriteInterval']

    if rm_data['monitorVTKPlane'] == False:
        return 
    
    if len(vtk_planes)==0: 
        return

    #Write dict files for wind profiles
    for pln in vtk_planes:
        #Open the template file (OpenFOAM file) for manipulation
        dict_file = open(template_dict_path + "/vtkPlaneTemplate", "r")

        dict_lines = dict_file.readlines()
        dict_file.close()
        
        #Write writeControl 
        start_index = foam.find_keyword_line(dict_lines, "writeControl") 
        if solver_type=="pimpleFoam":
            dict_lines[start_index] = "    writeControl \t{};\n".format("adjustableRunTime")
        else:
            dict_lines[start_index] = "    writeControl \t{};\n".format("timeStep")  

        #Write writeInterval
        start_index = foam.find_keyword_line(dict_lines, "writeInterval")     
        if solver_type=="pimpleFoam":
            dict_lines[start_index] = "    writeInterval \t{:.6f};\n".format(write_interval*time_step)
        else:
            dict_lines[start_index] = "    writeInterval \t{};\n".format(write_interval)

        #Write start and end time for the section  
        start_time = pln['startTime']
        end_time = pln['endTime']
        start_index = foam.find_keyword_line(dict_lines, "timeStart") 
        dict_lines[start_index] = "    timeStart \t\t{:.6f};\n".format(start_time)   

        start_index = foam.find_keyword_line(dict_lines, "timeEnd") 
        dict_lines[start_index] = "    timeEnd \t\t{:.6f};\n".format(end_time)   

        #Write name of the profile 
        name = pln["name"]
        start_index = foam.find_keyword_line(dict_lines, "planeName") 
        dict_lines[start_index] = "{}\n".format(name) 

        #Write field type 
        field_type = pln["field"]
        start_index = foam.find_keyword_line(dict_lines, "fields") 

        if field_type=="Velocity":
            dict_lines[start_index] = "    fields \t\t({});\n".format("U")
        if field_type=="Pressure":
            dict_lines[start_index] = "    fields \t\t({});\n".format("p")

        #Write normal and point coordinates
        point_x = pln["pointX"]
        point_y = pln["pointY"]
        point_z = pln["pointZ"]

        normal_axis = pln["normalAxis"]

        start_index = foam.find_keyword_line(dict_lines, "point")    
        dict_lines[start_index] = "\t    point\t\t({:.6f} {:.6f} {:.6f});\n".format(point_x, point_y, point_z)

        start_index = foam.find_keyword_line(dict_lines, "normal")  
        if normal_axis=="X":  
            dict_lines[start_index] = "\t    normal\t\t({} {} {});\n".format(1, 0, 0)
        if normal_axis=="Y":  
            dict_lines[start_index] = "\t    normal\t\t({} {} {});\n".format(0, 1, 0)
        if normal_axis=="Z":  
            dict_lines[start_index] = "\t    normal\t\t({} {} {});\n".format(0, 0, 1)

        #Write edited dict to file
        write_file_name = case_path + "/system/" + name
        
        if os.path.exists(write_file_name):
            os.remove(write_file_name)
        
        output_file = open(write_file_name, "w+")
        for line in dict_lines:
            output_file.write(line)
        output_file.close()
    
    
def write_momentumTransport_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    turb_data = json_data["turbulenceModeling"]
      
    simulation_type = turb_data['simulationType']
    RANS_type = turb_data['RANSModelType']
    LES_type = turb_data['LESModelType']
    DES_type = turb_data['DESModelType']

    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/momentumTransportTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    #Write type of the simulation 
    start_index = foam.find_keyword_line(dict_lines, "simulationType") 
    dict_lines[start_index] = "simulationType \t{};\n".format("RAS" if simulation_type=="RANS" else simulation_type)
    
    if simulation_type=="RANS":
        #Write RANS model type 
        start_index = foam.find_keyword_line(dict_lines, "RAS") + 2
        added_part = "    model \t{};\n".format(RANS_type)
        dict_lines.insert(start_index, added_part)
        
    elif simulation_type=="LES":
        #Write LES SGS model type 
        start_index = foam.find_keyword_line(dict_lines, "LES") + 2
        added_part = "    model \t{};\n".format(LES_type)
        dict_lines.insert(start_index, added_part)
    
    elif simulation_type=="DES":
        #Write DES model type 
        start_index = foam.find_keyword_line(dict_lines, "LES") + 2
        added_part = "    model \t{};\n".format(DES_type)
        dict_lines.insert(start_index, added_part)

    #Write edited dict to file
    write_file_name = case_path + "/constant/momentumTransport"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    
def write_physicalProperties_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    wc_data = json_data["windCharacteristics"]
      
    
    kinematic_viscosity = wc_data['kinematicViscosity']

    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/physicalPropertiesTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    

    #Write type of the simulation 
    start_index = foam.find_keyword_line(dict_lines, "nu") 
    dict_lines[start_index] = "nu\t\t[0 2 -1 0 0 0 0] {:.4e};\n".format(kinematic_viscosity)


    #Write edited dict to file
    write_file_name = case_path + "/constant/physicalProperties"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()
    

def write_transportProperties_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    wc_data = json_data["windCharacteristics"]
      
    
    kinematic_viscosity = wc_data['kinematicViscosity']

    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/transportPropertiesTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    

    #Write type of the simulation 
    start_index = foam.find_keyword_line(dict_lines, "nu") 
    dict_lines[start_index] = "nu\t\t[0 2 -1 0 0 0 0] {:.3e};\n".format(kinematic_viscosity)


    #Write edited dict to file
    write_file_name = case_path + "/constant/transportProperties"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()

def write_fvSchemes_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    turb_data = json_data["turbulenceModeling"]
      
    
    simulation_type = turb_data['simulationType']

    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/fvSchemesTemplate{}".format(simulation_type), "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    

    #Write edited dict to file
    write_file_name = case_path + "/system/fvSchemes"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()    
    
def write_decomposeParDict_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    ns_data = json_data["numericalSetup"]
      
    num_processors = ns_data['numProcessors']

    
    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/decomposeParDictTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    #Write number of sub-domains
    start_index = foam.find_keyword_line(dict_lines, "numberOfSubdomains") 
    dict_lines[start_index] = "numberOfSubdomains\t{};\n".format(num_processors)
    
    #Write method of decomposition
    start_index = foam.find_keyword_line(dict_lines, "decomposer") 
    dict_lines[start_index] = "decomposer\t\t{};\n".format("scotch")

    #Write method of decomposition for OF-V9 and lower compatability
    start_index = foam.find_keyword_line(dict_lines, "method") 
    dict_lines[start_index] = "method\t\t{};\n".format("scotch")
    

    #Write edited dict to file
    write_file_name = case_path + "/system/decomposeParDict"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()    
    
def write_DFSRTurbDict_file(input_json_path, template_dict_path, case_path):

    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)
    
    fmax = 200.0

    # Returns JSON object as a dictionary
    wc_data = json_data["windCharacteristics"]
    ns_data = json_data["numericalSetup"]
      
    wind_speed = wc_data['referenceWindSpeed']
    duration = ns_data['duration']
    
    #Generate a little longer duration to be safe
    duration = duration*1.010

    #Open the template file (OpenFOAM file) for manipulation
    dict_file = open(template_dict_path + "/DFSRTurbDictTemplate", "r")

    dict_lines = dict_file.readlines()
    dict_file.close()
    
    #Write the end time
    start_index = foam.find_keyword_line(dict_lines, "endTime") 
    dict_lines[start_index] = "endTime\t\t\t{:.4f};\n".format(duration)
    
    #Write patch name
    start_index = foam.find_keyword_line(dict_lines, "patchName") 
    dict_lines[start_index] = "patchName\t\t\"{}\";\n".format("inlet")

    #Write cohUav 
    start_index = foam.find_keyword_line(dict_lines, "cohUav") 
    dict_lines[start_index] = "cohUav\t\t\t{:.4f};\n".format(wind_speed)
    
    #Write fmax 
    start_index = foam.find_keyword_line(dict_lines, "fMax") 
    dict_lines[start_index] = "fMax\t\t\t{:.4f};\n".format(fmax)  
    
    #Write time step 
    start_index = foam.find_keyword_line(dict_lines, "timeStep") 
    dict_lines[start_index] = "timeStep\t\t{:.4f};\n".format(1.0/fmax)

    #Write edited dict to file
    write_file_name = case_path + "/constant/DFSRTurbDict"
    
    if os.path.exists(write_file_name):
        os.remove(write_file_name)
    
    output_file = open(write_file_name, "w+")
    for line in dict_lines:
        output_file.write(line)
    output_file.close()    
    

if __name__ == '__main__':    
    
    input_args = sys.argv

    # Set filenames
    input_json_path = sys.argv[1]
    template_dict_path = sys.argv[2]
    case_path = sys.argv[3]
    
    
    # input_json_path = "/home/abiy/Documents/WE-UQ/LocalWorkDir/EmptyDomainCFD/constant/simCenter/input"
    # template_dict_path = "/home/abiy/SimCenter/SourceCode/NHERI-SimCenter/SimCenterBackendApplications/applications/createEVENT/EmptyDomainCFD/templateOF10Dicts"
    # case_path = "/home/abiy/Documents/WE-UQ/LocalWorkDir/EmptyDomainCFD"
    
    # data_path = os.getcwd()
    # script_path = os.path.dirname(os.path.realpath(__file__))
    
    
    #Create case director
    # set up goes here 

    
    
    #Read JSON data
    with open(input_json_path + "/EmptyDomainCFD.json") as json_file:
        json_data =  json.load(json_file)

    # Returns JSON object as a dictionary
    turb_data = json_data["turbulenceModeling"]
       
    simulation_type = turb_data['simulationType']
    RANS_type = turb_data['RANSModelType']
    LES_type = turb_data['LESModelType']
    
    #Write blockMesh
    write_block_mesh_dict(input_json_path, template_dict_path, case_path)

    #Create and write the SnappyHexMeshDict file
    write_snappy_hex_mesh_dict(input_json_path, template_dict_path, case_path)
    
    #Write files in "0" directory
    write_U_file(input_json_path, template_dict_path, case_path)
    write_p_file(input_json_path, template_dict_path, case_path)
    write_nut_file(input_json_path, template_dict_path, case_path)
    write_k_file(input_json_path, template_dict_path, case_path)
    
    if simulation_type == "RANS" and RANS_type=="kEpsilon":
        write_epsilon_file(input_json_path, template_dict_path, case_path)

    #Write control dict
    write_controlDict_file(input_json_path, template_dict_path, case_path)
    
    #Write results to be monitored
    write_wind_profiles_file(input_json_path, template_dict_path, case_path)

    write_vtk_plane_file(input_json_path, template_dict_path, case_path)
    
    #Write fvSolution dict
    write_fvSolution_file(input_json_path, template_dict_path, case_path)

    #Write fvSchemes dict
    write_fvSchemes_file(input_json_path, template_dict_path, case_path)

    #Write momentumTransport dict
    write_momentumTransport_file(input_json_path, template_dict_path, case_path)
    
    #Write physicalProperties dict
    write_physicalProperties_file(input_json_path, template_dict_path, case_path)
    
    #Write transportProperties (physicalProperties in OF-10) dict for OpenFOAM-9 and below
    write_transportProperties_file(input_json_path, template_dict_path, case_path)
    
    #Write decomposeParDict
    write_decomposeParDict_file(input_json_path, template_dict_path, case_path)
    
    #Write DFSRTurb dict
    # write_DFSRTurbDict_file(input_json_path, template_dict_path, case_path)
    
    #Write TInf files 
    write_boundary_data_files(input_json_path, case_path)
