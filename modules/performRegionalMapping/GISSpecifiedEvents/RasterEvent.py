#  # noqa: INP001, D100
# Copyright (c) 2018 Leland Stanford Junior University
# Copyright (c) 2018 The Regents of the University of California
#
# This file is part of the SimCenter Backend Applications
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# You should have received a copy of the BSD 3-Clause License along with
# this file. If not, see <http://www.opensource.org/licenses/>.
#
# Contributors:
# Stevan Gavrilovic
#

import argparse
import json, csv
from pathlib import Path
import rasterio
import pyproj
from rasterio.transform import rowcol


def sample_raster_at_latlon(src, lat, lon):
    # Get the row and column indices in the raster
    row, col = rowcol(src.transform, lon, lat)  # Note the order: lon, lat

    # Ensure the indices are within the bounds of the raster
    if row < 0 or row >= src.height or col < 0 or col >= src.width:
        raise IndexError('Transformed coordinates are out of raster bounds')

    # Read the raster value at the given row and column
    raster_value = src.read(1)[row, col]

    return raster_value


def create_event(asset_file, event_grid_file):  # noqa: C901, N803, D103
    # read the event grid data file
    event_grid_path = Path(event_grid_file).resolve()
    event_dir = event_grid_path.parent
    event_grid_file = event_grid_path.name

    src = rasterio.open(event_grid_path)

    # Get the raster's CRS
    raster_crs = pyproj.CRS.from_wkt(src.crs.to_wkt())

    # Define the source CRS (EPSG:4326)
    src_crs = pyproj.CRS('EPSG:4326')

    # Transform the lat/lon to the raster's coordinate system
    transformer = pyproj.Transformer.from_crs(src_crs, raster_crs, always_xy=True)

    # iterate through the assets and store the selected events in the AIM
    with open(asset_file, encoding='utf-8') as f:  # noqa: PTH123
        asset_dict = json.load(f)

    data_final = [
        ['GP_file', 'Latitude', 'Longitude'],
    ]

    # Iterate through each asset
    for asset in asset_dict:
        asset_id = asset['id']
        asset_file_path = asset['file']

        # Load the corresponding file for each asset
        with open(asset_file_path, encoding='utf-8') as asset_file:
            # Load the asset data
            asset_data = json.load(asset_file)

            im_tag = asset_data['RegionalEvent']['intensityMeasures'][0]

            # Extract the latitude and longitude
            lat = float(asset_data['GeneralInformation']['location']['latitude'])
            lon = float(asset_data['GeneralInformation']['location']['longitude'])

            # Transform the coordinates
            lon_transformed, lat_transformed = transformer.transform(lon, lat)

            # Check if the transformed coordinates are within the raster bounds
            bounds = src.bounds
            if (
                bounds.left <= lon_transformed <= bounds.right
                and bounds.bottom <= lat_transformed <= bounds.top
            ):
                try:
                    val = sample_raster_at_latlon(
                        src=src, lat=lat_transformed, lon=lon_transformed
                    )

                    data = [[im_tag], [val]]

                    # Save the simcenter file name
                    file_name = f'Site_{asset_id}.csvx{0}x{int(asset_id):05d}'

                    data_final.append([file_name, lat, lon])

                    csv_save_path = event_dir / f'Site_{asset_id}.csv'
                    with open(csv_save_path, 'w', newline='') as file:
                        # Create a CSV writer object
                        writer = csv.writer(file)

                        # Write the data to the CSV file
                        writer.writerows(data)

                    # prepare a dictionary of events
                    event_list_json = [[file_name, 1.0]]

                    asset_data['Events'] = [{}]
                    asset_data['Events'][0] = {
                        'EventFolderPath': str(event_dir),
                        'Events': event_list_json,
                        'type': 'intensityMeasure',
                    }

                    with open(asset_file_path, 'w', encoding='utf-8') as f:  # noqa: PTH123
                        json.dump(asset_data, f, indent=2)

                except IndexError as e:
                    print(f'Error for asset ID {asset_id}: {e}')
            else:
                print(f'Asset ID: {asset_id} is outside the raster bounds')

        # # save the event dictionary to the BIM
        # asset_data['Events'] = [{}]
        # asset_data['Events'][0] = {
        #     # "EventClassification": "Earthquake",
        #     'EventFolderPath': str(event_dir),
        #     'Events': event_list_json,
        #     'type': event_type,
        #     # "type": "SimCenterEvents"
        # }

        # with open(asset_file, 'w', encoding='utf-8') as f:  # noqa: PTH123
        #     json.dump(asset_data, f, indent=2)

    # Save the final event grid
    csv_save_path = event_dir / 'EventGrid.csv'
    with open(csv_save_path, 'w', newline='') as file:
        # Create a CSV writer object
        writer = csv.writer(file)

        # Write the data to the CSV file
        writer.writerows(data_final)

    # Perform cleanup
    src.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assetFile')
    parser.add_argument('--filenameEVENTgrid')
    args = parser.parse_args()

    create_event(args.assetFile, args.filenameEVENTgrid)
