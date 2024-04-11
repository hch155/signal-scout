from app import app
from models import BaseStation
from database import db
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
import pandas as pd
import os
import re

def dms_to_decimal(dms_str):
    """Convert DMS (Degree-minute-second) string to decimal coordinates, as SQLAlchemy expects float """
    dms_str = re.sub(r'\s', '', dms_str)
    sign = -1 if re.search('[SW]', dms_str) else 1
    numbers = list(filter(len, re.split('\D+', dms_str, maxsplit=4)))
    degree = numbers[0]
    minute = numbers[1] if len(numbers) > 1 else '0'
    second = numbers[2] if len(numbers) > 2 else '0'
    return sign * (int(degree) + float(minute) / 60 + float(second) / 3600)

def extract_frequency_band(filename):
    """
    Extract the frequency band from the filename.
    Assuming the format is 'bandName_restOfTheFilename.xlsx'
    """
    return filename.split('_')[0]

def determine_rat(freq_band):
    freq_band_upper = freq_band.upper()
    # Check the start of the string
    if freq_band_upper.startswith('GSM'):
        return '2G'
    elif freq_band_upper.startswith('LTE'):
        return '4G'
    elif freq_band_upper.startswith('5G'):
        return '5G'
    else:
        return 'Unknown'

def read_and_process_excel(directory):
    """
    Read and process all Excel files in the specified directory.
    Combine them into a single DataFrame.
    """
    all_data = []
    for filename in os.listdir(directory):
        if filename.endswith('.xlsx'):
            file_path = os.path.join(directory, filename)
            df = pd.read_excel(file_path)

            # remove rows where all elements are NaN (entirely empty rows)
            df = df.dropna(how='all')
            
            # Extract frequency band from filename and add it as a column
            freq_band = extract_frequency_band(filename).upper()
            df['frequency_band'] = freq_band

            all_data.append(df)

    combined_df = pd.concat(all_data, axis=0, ignore_index=True)
    combined_df = combined_df.drop_duplicates(subset=['IdStacji', 'frequency_band'], keep='first')
    return combined_df

def populate_database(combined_df):
    """
    Populate the database with data from the combined DataFrame.
    """
    with app.app_context():
        db.create_all() 

        combined_df['Szer geogr stacji'] = combined_df['Szer geogr stacji'].apply(dms_to_decimal)
        combined_df['Dł geogr stacji'] = combined_df['Dł geogr stacji'].apply(dms_to_decimal)

        # sorting key for frequency bands
        def sorting_key(x):
            starts_with_5 = x.startswith('5')
            contains_LTE = 'LTE' in x
            ends_with_GSM = x.endswith('GSM')
            
            # Extract numeric part for sorting, if present
            numeric_part = int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0

            # Create a tuple that represents the sorting priority
            # Prioritize by starts_with_5 (True first), then not contains_LTE (False first for LTE),
            # then ends_with_GSM (True last), and finally by numeric_part in descending order
            return (not starts_with_5, not contains_LTE, ends_with_GSM, -numeric_part)

        combined_df['sorting_key'] = combined_df['frequency_band'].apply(sorting_key)

        # Sort by coordinates first, then by the custom sorting key for frequency bands
        combined_df.sort_values(by=['Szer geogr stacji', 'Dł geogr stacji', 'sorting_key'], inplace=True)

        # Drop the sorting_key column if it's no longer needed
        combined_df.drop('sorting_key', axis=1, inplace=True)

        for _, row in combined_df.iterrows():
            try:
                rat = determine_rat(row['frequency_band'])
                
                station = BaseStation(
                    latitude=row['Szer geogr stacji'],
                    longitude=row['Dł geogr stacji'],
                    frequency_band=row['frequency_band'],
                    rat=rat, 
                    basestation_id=row.get('IdStacji'),             # Real base station ID
                    city=row.get('Miejscowość'),         
                    service_provider=row.get('Nazwa Operatora'),    # name of ISP
                    location=str(row.get('Lokalizacja')),
                    frequency_band_count=-1,
                    latitude_segment=-1  
                )
                db.session.add(station)

            except ValueError as e:
                # Handle or log the error
                print(f"Error processing row: {e}")
                continue 
        db.session.commit()

def assign_freq_band_count():
    with app.app_context():
        # Fetch the distinct frequency band count for each base station
        station_band_counts = db.session.query(
            BaseStation.basestation_id,
            func.count(BaseStation.frequency_band.distinct()).label('band_count')
        ).group_by(BaseStation.basestation_id).all()
        
        # Update each station with its band count 
        for basestation_id, band_count in station_band_counts:
            # Update the station's band count
            db.session.query(BaseStation).filter_by(basestation_id=basestation_id).update(
                {"frequency_band_count": band_count}
            )
        
        db.session.commit()

def get_latitude_segment(latitude):
    """Returns the segment index for a given latitude."""
    base_latitude = 49.0  # Starting latitude
    segment_size = 0.3  # Size of each latitude segment // 33.(3) km
    return int((latitude - base_latitude) / segment_size)

def assign_latitude_segments():
    with app.app_context():
        stations = db.session.query(BaseStation).all()
        
        for station in stations:
            latitude_segment = get_latitude_segment(station.latitude)
            
            # Update the station's latitude_segment
            station.latitude_segment = latitude_segment
        
        db.session.commit()

def main():
    directory = 'base_station_data'
    combined_df = read_and_process_excel(directory)
    populate_database(combined_df)
    assign_freq_band_count()
    assign_latitude_segments()

if __name__ == '__main__':
    main()
