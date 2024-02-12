from app import app
from models import db, BaseStation
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
                rat = determine_rat(row['frequency_band'])

                station = BaseStation(
                    latitude=latitude_decimal,
                    longitude=longitude_decimal,
                    frequency_band=row['frequency_band'],
                    rat=rat, 
                    basestation_id=row.get('IdStacji'),             # Real base station ID
                    city=row.get('Miejscowość'),         
                    service_provider=row.get('Nazwa Operatora'),    # name of ISP
                    location=row.get('Lokalizacja')
                     
                )
                db.session.add(station)

            except ValueError as e:
                # Handle or log the error
                print(f"Error processing row: {e}")
                continue 
        db.session.commit()

def main():
    directory = 'base_station_data'
    combined_df = read_and_process_excel(directory)
    populate_database(combined_df)

if __name__ == '__main__':
    main()
