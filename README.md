# Signal-Scout 

Signal-Scout is a web application designed to help users find the nearest base stations for various service providers, ensuring optimal signal strength for mobile devices. This application is particularly useful for travelers or anyone needing to stay connected in different locations.

## Features

- Interactive map displaying base stations near the user's location
- Information on service providers, frequency bands and base station locations
- Tips for adjusting equipment to achieve the best signal strength

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Python 3.8 or higher
- pip and virtualenv
- Docker (optional, for containerization)

## Installation

1. **Clone the repository:**
   
   ```bash
   git clone https://github.com/hch155/signal-scout.git
   cd signal-scout

2. **Create and activate a virtual environment:**
   
   For macOS/Linux:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
   For Windows:
   ```bash
   python3 -m venv venv
   venv\Scripts\activate
   ```
   
3. **Install the required dependencies:**
   ```bash
   pip install -r requirements.txt
    ```
## Running the Application

To run Signal-Scout, execute:

    cd src
    python app.py    
    
Access the web application by navigating to http://localhost:8080 in your web browser.

## Docker Deployment 

If you prefer to use Docker, you can build and run the application as a Docker container:
    
    docker build -t signal-scout .
    docker run -p 8080:8080 signal-scout
    

If you have any questions or suggestions, please contact me at hcylwik@gmail.com

