# database_setup.py
from app import db, BaseStation, app
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
            
            # Extract frequency band from filename and add it as a column
            freq_band = extract_frequency_band(filename)
            df['frequency_band'] = freq_band

            all_data.append(df)

    return pd.concat(all_data, axis=0)

def populate_database(combined_df):
    """
    Populate the database with data from the combined DataFrame.
    """
    with app.app_context():
        db.create_all()  # Create database tables

        for _, row in combined_df.iterrows():
            try:
                latitude_decimal = dms_to_decimal(row['Szer geogr stacji'])
                longitude_decimal = dms_to_decimal(row['Dł geogr stacji'])
            except ValueError:
                # Handle or log the error
                continue

            station = BaseStation(
                latitude=latitude_decimal,
                longitude=longitude_decimal,
                frequency_band=row['frequency_band']
            )
            db.session.add(station)
        db.session.commit()

def find_nearest_stations(user_lat, user_lon, limit=5):
    

def main():
    directory = 'base_station_data'
    combined_df = read_and_process_excel(directory)
    populate_database(combined_df)

if __name__ == '__main__':
    main()
