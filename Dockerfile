# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install any needed packages specified in requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Run the app
# Cloud Run needs to be able to communicate with the application via HTTP.
# We'll use a simple HTTP server to handle webhooks.
CMD python main.py
