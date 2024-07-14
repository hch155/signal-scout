# Use an official Python runtime as a parent image
FROM python:3.12.2-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Env variable
ENV PYTHONPATH=/usr/src/app/src

# Run app.py when the container launches using Gunicorn
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8080", "src.app:app"]
