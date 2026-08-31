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

from pymilvus import DataType, MilvusClient
import os
from utils import API
import constants as const

collection_name = os.getenv(const.COLLECTION_NAME)
create_collection = os.getenv(const.CREATE_COLLECTION, True)


def upsert_vector_for_onprem(mc, embed, orgID, keyID, api: API, tenant, visibilityRoles):
    if create_collection:
        has = mc.has_collection(collection_name)
        if not has:
            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=100)
            schema.add_field(field_name="metadata", datatype=DataType.JSON, max_length=2000)
            schema.add_field(field_name="api_type", datatype=DataType.VARCHAR, max_length=100)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=1536)
            schema.add_field(field_name="page_content", datatype=DataType.VARCHAR, max_length=10000)
            schema.add_field(field_name="org_id", datatype=DataType.VARCHAR, max_length=512)
            schema.add_field(field_name="key_id", datatype=DataType.VARCHAR, max_length=512, is_partition_key=True)
            schema.add_field(field_name="tenant_domain", datatype=DataType.VARCHAR, max_length=512)
            schema.add_field(field_name="visibility_roles", datatype=DataType.ARRAY, element_type=DataType.VARCHAR, max_length=100, max_capacity=100)

            index_params = mc.prepare_index_params()

            index_params.add_index(
                field_name="vector",
                index_type="AUTOINDEX",
                metric_type="L2"
            )
            mc.create_collection(
                collection_name=collection_name,
                metric_type="COSINE",
                schema=schema,
                index_params=index_params
            )
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
        "org_id": orgID,
        "key_id": keyID,
        "tenant_domain": tenant,
        "visibility_roles": visibilityRoles
    }
    response = mc.upsert(collection_name=collection_name, data=payload)
    return response


def delete_vector(mc, uuid, record_id):
    uuid = [record_id + id for id in uuid]
    response = mc.delete(
        collection_name=collection_name,
        ids=uuid
    )
    return response


def upsert_bulk_vector_for_onprem(mc, payload):
    if create_collection:
        has = mc.has_collection(collection_name)
        if not has:
            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=100)
            schema.add_field(field_name="metadata", datatype=DataType.JSON, max_length=2000)
            schema.add_field(field_name="api_type", datatype=DataType.VARCHAR, max_length=100)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=1536)
            schema.add_field(field_name="page_content", datatype=DataType.VARCHAR, max_length=10000)
            schema.add_field(field_name="org_id", datatype=DataType.VARCHAR, max_length=512)
            schema.add_field(field_name="key_id", datatype=DataType.VARCHAR, max_length=512, is_partition_key=True)
            schema.add_field(field_name="tenant_domain", datatype=DataType.VARCHAR, max_length=512)
            schema.add_field(field_name="visibility_roles", datatype=DataType.ARRAY, element_type=DataType.VARCHAR, max_length=100, max_capacity=100)

            index_params = mc.prepare_index_params()

            index_params.add_index(
                field_name="vector",
                index_type="AUTOINDEX",
                metric_type="L2"
            )
            mc.create_collection(
                collection_name=collection_name,
                metric_type="COSINE",
                schema=schema,
                index_params=index_params
            )

    response = mc.upsert(collection_name=collection_name, data=payload)
    return response

def delete_bulk_vector_for_onprem(mc, orgId, keyId, tenantDomain):
    response = mc.delete(
        collection_name=collection_name,
        filter=f"key_id == '{keyId}' && tenant_domain == '{tenantDomain}'"
    )
    return response


def get_vector_count_for_key(mc, key_id):
    response = mc.query(
        collection_name=collection_name,
        filter=f'(key_id == "{key_id}")',
        output_fields=["count(*)"],
    )
    return response[0]["count(*)"]
