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

# environment variable names
MILVERSE_API_KEY = "MILVERSE_API_KEY"
MILVERSE_URL = "MILVERSE_URL"
EXCLUDED_ORG_LIST = "EXCLUDED_ORG_LIST"
COLLECTION_NAME = "COLLECTION_NAME"
CREATE_COLLECTION = "CREATE_COLLECTION"
# Maximum number of APIs a single keyID may index, reported by GET /vectors/count.
# Sourced only from this service's configuration; no request field carries it.
API_INDEX_LIMIT = "API_INDEX_LIMIT"

# API types
APIPRODUCT = "APIPRODUCT"
REST = "REST"
HTTP = "HTTP"
SOAP = "SOAP"
SOAPTOREST = "SOAPTOREST"
GRAPHQL = "GRAPHQL"
ASYNC = "ASYNC"
WS = "WS"
WEBSUB = "WEBSUB"
SSE = "SSE"
WEBHOOK = "WEBHOOK"

# API information fields
API_NAME = "api_name"
API_TYPE = "api_type"
API_VERSION = "version"
API_UUID = "api_uuid"
API_SPEC = "api_spec"
APIM_DESCRIPTION = "apim_description"

ORG_ID = "org_id"
UUID = "uuid"
DESCRIPTION = "description"

MESSAGE = "message"

# This list is added to exclude the info level http logs from FastAPI
EXCLUDED_ENDPOINTS = ["/vectors", "/vectors/bulk", "/vectors/count",
                      "/vectors/{uuid}", "/health"]
