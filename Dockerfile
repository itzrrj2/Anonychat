FROM python:3.10-slim

# Create working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source code
COPY . .

# Run the bot
CMD ["python", "main.py"]
