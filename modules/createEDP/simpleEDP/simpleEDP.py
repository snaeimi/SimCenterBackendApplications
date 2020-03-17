from __future__ import division, print_function
import os, sys
if sys.version.startswith('2'):
    range=xrange
    string_types = basestring
else:
    string_types = str

import argparse, posixpath, ntpath, json

def write_RV(BIM_input_path, EDP_input_path, EDP_type):
    
    # load the BIM file
    with open(BIM_input_path, 'r') as f:
        BIM_in = json.load(f)

    EDP_list = []
    if "EDP" in BIM_in.keys():
        for edp in BIM_in["EDP"]:
            EDP_list.append({
                "type": edp["type"],
                "cline": edp.get("cline", "1"),
                "floor": edp.get("floor", "1"),
                "dofs": edp.get("dofs", [1,]),  
                "scalar_data": [],         
            })
    else:
        EDP_list.append({
            "type": EDP_type,
            "cline": "1",
            "floor": "1",
            "dofs": [1,],
            "scalar_data": [],         
        })

    EDP_json = {
        "RandomVariables": [],
        "total_number_edp": len(EDP_list),
        "EngineeringDemandParameters": [{
            "responses": EDP_list
        },]
    }

    with open(EDP_input_path, 'w') as f:
        json.dump(EDP_json, f, indent=2)

def create_EDP(BIM_input_path, EDP_input_path, EDP_type):
    pass   

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--filenameBIM', default=None)
    parser.add_argument('--filenameSAM', default=None)
    parser.add_argument('--filenameEVENT')
    parser.add_argument('--filenameEDP')
    parser.add_argument('--type')
    parser.add_argument('--getRV', nargs='?', const=True, default=False)
    args = parser.parse_args()

    if args.getRV:
        sys.exit(write_RV(args.filenameBIM, args.filenameEDP, args.type))
    else:
        sys.exit(create_EDP(args.filenameBIM, args.filenameEDP, args.type))