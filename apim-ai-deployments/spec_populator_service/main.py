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
import logging

from fastapi import FastAPI, HTTPException, Query
from typing import Dict, Any, Optional, List
from enum import Enum
import asyncio
from functools import partial
import os
from log_filters import EndpointFilter

from pydantic import BaseModel, ConfigDict, model_validator
from pymilvus import MilvusClient

from milvus import upsert_vector_for_onprem, delete_vector, \
    upsert_bulk_vector_for_onprem, get_vector_count_for_key, delete_bulk_vector_for_onprem
from utils import get_emb_model, pre_process_openapi, pre_process_graphql_sdl, \
    pre_process_asyncapi_def, API

import constants as const

embed = get_emb_model()
api_key = os.getenv(const.MILVERSE_API_KEY)
url = os.getenv(const.MILVERSE_URL)

# Maximum number of APIs a single keyID may index, reported by GET /vectors/count.
api_index_limit = int(os.getenv(const.API_INDEX_LIMIT, "100"))

app = FastAPI()

# Setting log levels
log_level = os.getenv('LOG_LEVEL', logging.INFO)
logging.basicConfig(level=log_level)
for logger_name in logging.root.manager.loggerDict:
    logging.getLogger(logger_name).setLevel(log_level)

logging.getLogger("uvicorn.access").addFilter(EndpointFilter(const.EXCLUDED_ENDPOINTS))


class ApiType(str, Enum):
    HTTP = "HTTP"
    REST = "REST"
    SOAP = "SOAP"
    SOAPTOREST = "SOAPTOREST"
    APIPRODUCT = "APIPRODUCT"
    GRAPHQL = "GRAPHQL"
    ASYNC = "ASYNC"
    WS = "WS"
    WEBSUB = "WEBSUB"
    SSE = "SSE"
    WEBHOOK = "WEBHOOK"


# Which definition field each api_type reads. api_type sent without its matching,
# non-null definition field is a request error (422).
SPEC_FIELD_BY_TYPE = {
    ApiType.HTTP: const.API_SPEC,
    ApiType.REST: const.API_SPEC,
    ApiType.SOAP: const.API_SPEC,
    ApiType.SOAPTOREST: const.API_SPEC,
    ApiType.APIPRODUCT: const.API_SPEC,
    ApiType.GRAPHQL: "sdl_schema",
    ApiType.ASYNC: "async_spec",
    ApiType.WS: "async_spec",
    ApiType.WEBSUB: "async_spec",
    ApiType.SSE: "async_spec",
    ApiType.WEBHOOK: "async_spec",
}


# request input format for a single API record. additionalProperties are allowed
# because the gateway proxies through any top-level fields API Manager's request
# property enricher adds; we read only what we need and ignore the rest.
class ApiRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    uuid: str
    api_name: str
    api_type: ApiType
    version: str
    # Required key, but frequently null: API Manager copies api.getDescription()
    # with no null guard. A null description is treated as absent, not rejected.
    description: Optional[str]
    tenant_domain: str
    api_spec: Optional[str] = None
    sdl_schema: Optional[str] = None
    async_spec: Optional[str] = None
    visibility_roles: Optional[str] = None
    apim_version: Optional[str] = None

    @model_validator(mode="after")
    def require_selected_definition(self):
        field = SPEC_FIELD_BY_TYPE[self.api_type]
        value = getattr(self, field)
        # Only the definition field selected by api_type may not be null/empty -
        # there is nothing to embed without it.
        if value is None or value == "":
            raise ValueError(
                f"'{field}' is required and must be non-null for api_type '{self.api_type.value}'"
            )
        return self


class BulkApiRecords(BaseModel):
    model_config = ConfigDict(extra="allow")

    apis: List[ApiRecord]


async def get_pre_processed_spec(api_details):
    api_type = api_details[const.API_TYPE]
    if api_type == const.APIPRODUCT:
        api_type = const.HTTP
        record = await pre_process_openapi(api_details[const.API_SPEC])
    elif api_type == const.REST or api_type == const.HTTP or api_type == const.SOAP or api_type == const.SOAPTOREST:
        record = await pre_process_openapi(api_details[const.API_SPEC])
    elif api_type == const.GRAPHQL:
        record = await pre_process_graphql_sdl(api_details["sdl_schema"])
    elif api_type == const.ASYNC or api_type == const.WS or api_type == const.WEBSUB or api_type == const.SSE or api_type == const.WEBHOOK:
        record = await pre_process_asyncapi_def(api_details["async_spec"])

    record[const.APIM_DESCRIPTION] = api_details[const.DESCRIPTION]
    api = API(
        id=api_details[const.UUID],
        # The actual version is used instead of what is in the Spec,
        # since we know this is the truth, and the spec version can be outdated
        version=api_details[const.API_VERSION],
        type=api_type,
        name=api_details[const.API_NAME],
        spec=record
    )
    return api


@app.post("/vectors", status_code=201)
async def add_vector(req: ApiRecord, keyID: str = Query(..., min_length=1, max_length=64)):
    mc = MilvusClient(uri=url, token=api_key)
    try:
        api = await get_pre_processed_spec(req.model_dump())

        loop = asyncio.get_event_loop()

        # Omitted / empty visibility_roles stores an empty role set, making the API
        # visible to everyone in the tenant.
        roles = req.visibility_roles.split(",") if req.visibility_roles else ['']

        # keyID is the whole of the scoping. org_id is retained internally only for
        # storage compatibility (never read back), so it is filled from keyID.
        response = await loop.run_in_executor(
            None,
            partial(upsert_vector_for_onprem, mc, embed, keyID, keyID, api, req.tenant_domain, roles)
        )

        return {const.MESSAGE: response}
    except Exception as e:
        logging.error(f"An error occurred while adding a vector: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mc.close()


@app.post("/vectors/bulk")
async def bulk_add_vector(req: BulkApiRecords, keyID: str = Query(..., min_length=1, max_length=64)):
    api_list = []

    for api_details in req.apis:
        api = await get_pre_processed_spec(api_details.model_dump())

        embedding_response = embed.embed_query(str(api.__dict__))
        payload = {
            "page_content": str(api.spec),
            "metadata": {
                "id": api.id,
                "api_name": api.name,
                "api_version": api.version,
                "api_type": api.type
            },
            "id": keyID + api.id,
            "vector": embedding_response,
            "api_type": api.type,
            "org_id": keyID,
            "key_id": keyID,
            "tenant_domain": api_details.tenant_domain,
            "visibility_roles": ''
        }

        if api_details.visibility_roles:
            payload["visibility_roles"] = api_details.visibility_roles.split(",")

        api_list.append(payload)

    mc = MilvusClient(uri=url, token=api_key)
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, partial(upsert_bulk_vector_for_onprem, mc, api_list))
        return {const.MESSAGE: response}
    except Exception as e:
        logging.error(f"An error occurred while adding bulk of vectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mc.close()


@app.delete("/vectors")
async def bulk_remove_vector(keyID: str = Query(..., min_length=1, max_length=64), tenant_domain: str = Query(..., min_length=1)):
    mc = MilvusClient(uri=url, token=api_key)
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(delete_bulk_vector_for_onprem, mc, keyID, keyID, tenant_domain)
        )
        return {const.MESSAGE: response}
    except Exception as e:
        logging.error(f"An error occurred while removing bulk of vectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mc.close()


@app.get("/health")
def health():
    """Check the api is running"""
    return {"status": "Running"}


@app.get("/vectors/count")
async def get_api_count_by_key(keyID: str = Query(..., min_length=1, max_length=64)):
    mc = MilvusClient(uri=url, token=api_key)
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, partial(get_vector_count_for_key, mc, keyID))
        logging.info(f"API count for keyID {keyID}: {response}")
        return {"count": response, "limit": api_index_limit}
    except Exception as e:
        logging.error(f"An error occurred while getting api count by key: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mc.close()


# Declared after /vectors/bulk and /vectors/count: both also match this {uuid}
# template, and FastAPI resolves routes in declaration order.
@app.delete("/vectors/{uuid}")
async def remove_vector(uuid: str, keyID: str = Query(..., min_length=1, max_length=64)):
    mc = MilvusClient(uri=url, token=api_key)
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, partial(delete_vector, mc, [uuid], keyID))
        return {const.MESSAGE: response}
    except Exception as e:
        logging.error(f"An error occurred while removing a vector: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mc.close()
