"""
Copyright (c) 2026, WSO2 LLC. (https://www.wso2.com).

WSO2 LLC. licenses this file to you under the Apache License,
Version 2.0 (the "License"); you may not use this file except
in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied. See the License for the
specific language governing permissions and limitations
under the License.
"""
import os
from dotenv import load_dotenv

load_dotenv()

ZILLIZ_CLOUD_URI = os.getenv('ZILLIZ_CLOUD_URI', "")
ZILLIZ_CLOUD_API_KEY = os.getenv('ZILLIZ_CLOUD_API_KEY', "")
AZURE_ENDPOINT = os.getenv('AZURE_ENDPOINT')
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_EMBEDDING_DEPLOYMENT = os.getenv('AZURE_EMBEDDING_DEPLOYMENT', "OpenAPIEmbeddings")
AZURE_CHAT_DEPLOYMENT = os.getenv('AZURE_CHAT_DEPLOYMENT', "APIM-Deployment")
AZURE_CHAT_VERSION = os.getenv('AZURE_CHAT_VERSION', "2025-04-01-preview")
PROXY_HEALTH_CHECK_CACHE_TTL = int(os.getenv('PROXY_HEALTH_CHECK_CACHE_TTL', '900'))
TOKEN_CACHE_SIZE = int(os.getenv("TOKEN_CACHE_SIZE", "50"))
TOKEN_CACHE_TTL = int(os.getenv("TOKEN_CACHE_TTL", "870"))

# azure openai proxy related env variables
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET") 
TOKEN_ENDPOINT_URL = os.getenv("TOKEN_ENDPOINT_URL")
AZURE_CHAT_PROXY_ENDPOINT = os.getenv("AZURE_CHAT_PROXY_ENDPOINT")
AZURE_EMBEDDING_PROXY_ENDPOINT = os.getenv('AZURE_EMBEDDING_PROXY_ENDPOINT')
