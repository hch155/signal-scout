import requests
import re
import os
from urllib.parse import urljoin

# Function to download files from a URL
def get_uke_raw_data(url, patterns, download_folder='./'):
    # Fetch the content of the URL
    response = requests.get(url)
    response.raise_for_status()  # Check if the request was successful
    
    # Find all the links in the content
    links = re.findall(r'href="([^"]+)"', response.text)
    
    # Compile regex patterns
    compiled_patterns = [re.compile(pattern) for pattern in patterns]
    
    for link in links:
        # Check if the link matches any of the patterns
        if any(pattern.search(link) for pattern in compiled_patterns):
            file_url = urljoin(url, link)  # Construct the full URL
            file_name = os.path.join(download_folder, link.split('/')[-1])
            
            # Download the file
            print(f'Downloading {file_url}...')
            file_response = requests.get(file_url)
            file_response.raise_for_status()  # Check if the request was successful
            
            # Save the file
            with open(file_name, 'wb') as file:
                file.write(file_response.content)
            print(f'Saved {file_name}')

# URL to access
url = 'https://bip.uke.gov.pl/pozwolenia-radiowe/wykaz-pozwolen-radiowych-tresci/stacje-gsm-umts-lte-oraz-cdma,12.html'

# Patterns to match in the filenames
patterns = [r'5g3600', r'5g2600', r'5g2100', r'5g1800', r'lte2600', r'lte2100', r'lte1800', r'lte900', r'lte800', r'gsm900']

get_uke_raw_data(url, patterns, download_folder='./')