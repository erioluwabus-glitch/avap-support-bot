import json
import os
from dotenv import load_dotenv
import base64
import binascii

load_dotenv()
GOOGLE_CREDENTIALS_STR = os.getenv('GOOGLE_CREDENTIALS')
try:
    dict_data = json.loads(GOOGLE_CREDENTIALS_STR)
    private_key = dict_data['private_key'].replace('\\n', '\n')  # Fix if needed
    pem_base64 = private_key.split('-----BEGIN PRIVATE KEY-----')[1].split('-----END PRIVATE KEY-----')[0].replace('\n', '').strip()
    base64.b64decode(pem_base64)
    print("Base64 is valid! Length:", len(pem_base64))
except Exception as e:
    print("Error:", e)