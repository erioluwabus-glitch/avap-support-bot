import json

# Use the correct path to your file
with open(r'C:\Users\ERI DANIEL\Downloads\avapsupportbot-471814-9308fa38e243.json', 'r') as f:
    data = json.load(f)

# Generate the escaped single-line string
escaped = json.dumps(data)
print("Copy this FULL string for GOOGLE_CREDENTIALS in .env (it should be very long):")
print(escaped)
