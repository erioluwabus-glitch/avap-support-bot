import json

# Paste your REAL downloaded JSON content here as a dict (replace placeholders)
credentials_data = {
    "type": "service_account",
    "project_id": "avapsupportbot-471814",
    "private_key_id": "5f7efb97b7fea215705...",  # Your real value
    "private_key": "-----BEGIN PRIVATE KEY-----\nYourFullBase64KeyHereWithNewlines\n-----END PRIVATE KEY-----",  # Paste the full key with actual \n
    "client_email": "avapsupportbotservice@avapsupportbot-471814.iam.gserviceaccount.com",
    "client_id": "your_client_id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/avapsupportbotservice%40avapsupportbot-471814.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"  # If present
}

# Generate escaped string
escaped = json.dumps(credentials_data)
print("Copy this for .env GOOGLE_CREDENTIALS:")
print(escaped)