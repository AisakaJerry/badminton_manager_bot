# Use an official Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set the working directory in the container
WORKDIR /app

# Install any needed packages specified in requirements.txt
COPY requirements.txt .
RUN apt-get update && apt-get upgrade -y && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Command to run the application using gunicorn
# The `main` module will be the entry point to your Python application
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 300 main:application
