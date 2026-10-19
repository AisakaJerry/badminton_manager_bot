# Use an official Python runtime as a parent image
FROM python:3.12-slim-bookworm

# Set the working directory in the container
WORKDIR /app

# Install any needed packages specified in requirements.txt.
# No apt step: nothing here needs OS packages, and the base image is rebuilt upstream with
# security updates. (An `apt-get upgrade` here broke the build once bullseye went EOL.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Command to run the application using gunicorn
# The `main` module will be the entry point to your Python application
CMD exec gunicorn --workers 1 --threads 8 --timeout 300 -k uvicorn.workers.UvicornWorker main:app