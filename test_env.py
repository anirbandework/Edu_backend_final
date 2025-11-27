#!/usr/bin/env python3

import os
from dotenv import load_dotenv

print("=== Environment Test ===")

# Load .env file
load_dotenv()

# Check all environment variables
print("Environment variables:")
for key in ['PERPLEXITY_API_KEY', 'DATABASE_URL', 'PORT']:
    value = os.getenv(key)
    if value:
        if 'API_KEY' in key:
            print(f"{key}: {value[:10]}...")
        else:
            print(f"{key}: {value}")
    else:
        print(f"{key}: NOT SET")

# Check if .env file exists
env_file = ".env"
if os.path.exists(env_file):
    print(f"\n.env file exists: {env_file}")
    with open(env_file, 'r') as f:
        content = f.read()
        if 'PERPLEXITY_API_KEY' in content:
            print("PERPLEXITY_API_KEY found in .env file")
        else:
            print("PERPLEXITY_API_KEY NOT found in .env file")
else:
    print(f"\n.env file NOT found: {env_file}")