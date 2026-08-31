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
from typing import List
import json
from langchain_openai import AzureChatOpenAI
from operator import itemgetter
from fastapi import FastAPI, Header
from pydantic import BaseModel, field_validator
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.output_parsers import StrOutputParser, BaseOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.runnables import RunnableParallel
from langchain.callbacks import get_openai_callback
import asyncio
from pydantic import BaseModel, field_validator
import requests

from functools import partial
from cachetools import cached, TTLCache

from langchain_azure_ai.embeddings import AzureAIEmbeddingsModel
from azure.core.credentials import AzureKeyCredential
from langchain_community.vectorstores import Milvus
from langchain.retrievers.multi_query import MultiQueryRetriever

from app.constants import *
import jwt
from app.prompts import qa_system_prompt_apim, \
    query_prompt_template, context_q_system_prompt

api = FastAPI(
    title="API Marketplace Chatbot",
    version="0.1.0",
)

# TODO: implement debug logging switch
collection_name = os.getenv("COLLECTION_NAME")


# request input format
class Query(BaseModel):
    query: str
    history: list
    tenant_domain: str
    user_roles: str

    @field_validator('history', mode='before')
    @classmethod
    def parse_history(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


@cached(cache=TTLCache(maxsize=2, ttl=PROXY_HEALTH_CHECK_CACHE_TTL))
def validate_endpoint(endpoint: str) -> bool:
    try:
        response = requests.options(endpoint, timeout=2)
        return response.status_code < 300
    except:
        return False

def _get_org_id_key(x_jwt_assertion: str):
    """Extract org_id from JWT assertion to use as cache key"""
    payload = jwt.decode(x_jwt_assertion, options={"verify_signature": False})
    aud = payload.get("aud")
    return aud[0]

@cached(cache=TTLCache(maxsize=TOKEN_CACHE_SIZE, ttl=TOKEN_CACHE_TTL), key=_get_org_id_key)
def exchange_assertion_for_api_key(x_jwt_assertion: str):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "subject_token": x_jwt_assertion,
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(TOKEN_ENDPOINT_URL, headers=headers, data=data)
    response.raise_for_status()
    return response.json().get("access_token")

def get_llm(x_jwt_assertion: str = None):
    """
    Get LLM client with automatic fallback from proxy to direct connection.
    If proxy is enabled but fails, it will automatically fallback to direct connection.
    """
    if USE_PROXY:
        api_key = exchange_assertion_for_api_key(x_jwt_assertion)
        if validate_endpoint(AZURE_CHAT_PROXY_ENDPOINT + "/openai/responses?api-version=2025-04-01-preview"):
            return AzureChatOpenAI(
                azure_endpoint=AZURE_CHAT_PROXY_ENDPOINT,
                azure_deployment=AZURE_CHAT_DEPLOYMENT,
                api_key=api_key,
                api_version=AZURE_CHAT_VERSION,
                output_version="responses/v1"
            )
        else:
            print(f"Warning: Proxy endpoint {AZURE_CHAT_PROXY_ENDPOINT} is not reachable, falling back to direct connection.")

    return AzureChatOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_deployment=AZURE_CHAT_DEPLOYMENT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_CHAT_VERSION,
        output_version="responses/v1"
    )

def get_embeddings(x_jwt_assertion: str = None):
    if USE_PROXY:
        if validate_endpoint(AZURE_EMBEDDING_PROXY_ENDPOINT + "/embeddings?api-version=2025-01-01-preview"):
            api_key = exchange_assertion_for_api_key(x_jwt_assertion)
            return AzureAIEmbeddingsModel(
                endpoint=AZURE_EMBEDDING_PROXY_ENDPOINT,
                credential=AzureKeyCredential(api_key),
                model=AZURE_EMBEDDING_DEPLOYMENT,
            )
        else:
            print(f"Warning: Proxy endpoint {AZURE_EMBEDDING_PROXY_ENDPOINT} is not reachable, falling back to direct connection.")

    return AzureAIEmbeddingsModel(
        model=AZURE_EMBEDDING_DEPLOYMENT,
        credential=AzureKeyCredential(AZURE_API_KEY),
        endpoint=AZURE_ENDPOINT + "/openai/deployments/" + AZURE_EMBEDDING_DEPLOYMENT,
    )

def get_vectorstore(x_jwt_assertion: str = None) -> Milvus:
    """Get or create cached APIM vectorstore instance"""
    return Milvus(
        get_embeddings(x_jwt_assertion),
        connection_args={
            "uri": ZILLIZ_CLOUD_URI,
            "token": ZILLIZ_CLOUD_API_KEY,
            "secure": True,
        },
        collection_name=collection_name,
        text_field="page_content",
        metadata_field="metadata"
    )

def get_retriever(llm, tenant_domain, partition_id, auth_token=None, user_roles ='') -> MultiQueryRetriever:
    # TODO: Try adding a Self Query retriever
    # Incorporate score based filtering mechanism once Milverse introduces it
    vectorstore = get_vectorstore(auth_token)

    if user_roles == '':
        retriever = vectorstore.as_retriever(search_type="similarity",
                                         search_kwargs={"k": 5,
                                                        "expr": 'key_id == "' + partition_id + '" && tenant_domain == "' + tenant_domain + '" && visibility_roles[0] == ""'})
    else:
        retriever = vectorstore.as_retriever(search_type="similarity",
                                         search_kwargs={"k": 5,
                                                        "expr": 'key_id == "' + partition_id + '" && tenant_domain == "' + tenant_domain + '" && ((visibility_roles[0] == "") || (array_contains_any(visibility_roles,'+user_roles+')))'})

    QUERY_PROMPT = PromptTemplate(
        input_variables=["question"],
        template=query_prompt_template,
    )

    class LineListOutputParser(BaseOutputParser[List[str]]):
        """Output parser for a list of lines."""

        def parse(self, text: str) -> List[str]:
            lines = text.strip().split("\n")
            return lines

    output_parser = LineListOutputParser()
    llm_chain = QUERY_PROMPT | llm | output_parser

    mq_retriever = MultiQueryRetriever(retriever=retriever, llm_chain=llm_chain, parser_key="lines")
    return mq_retriever


def format_docs(docs):
    if not docs:
        return ["No API information available!"]
    else:
        return "\n\n".join([str({"api_details": doc.metadata, "api_spec": doc.page_content}) for doc in docs])


def prepare_rag_chain(tenant_domain: str, partition_id: str, stream=False, auth_token=None, user_roles = ''):

    contextualize_q_system_prompt = context_q_system_prompt
    contextualize_q_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", contextualize_q_system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ]
    )

    llm = get_llm(auth_token)
    retriever = get_retriever(llm, tenant_domain, partition_id, auth_token, user_roles)
    qa_system_prompt = qa_system_prompt_apim

    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", qa_system_prompt),
            ("human", "{question}"),
        ]
    )

    _inputs = RunnableParallel(
        standalone_question=RunnablePassthrough.assign(
            chat_history=lambda x: x["chat_history"]
        )
                            | contextualize_q_prompt
                            | llm
                            | StrOutputParser(),
    )

    # def cond_input(input: dict):
    #     if input.get("chat_history"):
    #         return _inputs
    #     else:
    #         return input["question"]

    _context = {
        "context": itemgetter("standalone_question") | retriever | format_docs,
        "question": lambda x: x["standalone_question"],
    }
    rag_chain = _inputs | _context | qa_prompt | llm

    return rag_chain, llm


async def in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def prepare_history(history: list):
    return [(chat["role"], chat["content"]) for chat in history]


async def generate_response(
        user_roles: str, tenant_domain: str, message: str, history: list, partitionID: str, auth_token: str
):
    results = await asyncio.gather(
        in_thread(prepare_rag_chain, tenant_domain, partitionID, False, auth_token, user_roles),
        prepare_history(history),
    )
    rag_chain, llm = results[0]
    chat_history = results[1]

    try:
        with get_openai_callback() as cb:
                chain_response_raw = await rag_chain.ainvoke({
                    "question": message,
                    "chat_history": chat_history},
                    # config={
                    #     'callbacks': [ConsoleCallbackHandler()]
                    #     }
                )
                # chain_response_raw.content may be a list of blocks, extract text
                if hasattr(chain_response_raw, "content") and isinstance(chain_response_raw.content, list):
                    text_content = "".join(
                        block.get("text", "") for block in chain_response_raw.content if block.get("type") == "text"
                    )
                elif hasattr(chain_response_raw, "content") and isinstance(chain_response_raw.content, str):
                    text_content = chain_response_raw.content
                else:
                    text_content = str(chain_response_raw)
                chain_response = parse_json(text_content, cb)
        return chain_response
    finally:
        # Close the LLM client session to prevent unclosed connection warnings
        if hasattr(llm, 'aclose'):
            await llm.aclose()


def parse_json(json_resp, token_usage):
    # APIM's MarketplaceAssistantResponseDTO accepts exactly "response" and "apis"
    # (additionalProperties: false); any other top-level field aborts strict Jackson
    # deserialization on the platform side. Return only those two, whatever else the
    # model produced, so no stray field (e.g. "usage" or a top-level "apiName") leaks.

    # The model sometimes wraps its JSON answer in a ```json ... ``` markdown fence.
    # Strip it before parsing, otherwise json.loads fails and the whole fenced blob is
    # returned as `response` (which the Developer Portal then renders as raw JSON).
    cleaned = json_resp.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
    try:
        json_object = json.loads(cleaned)
    except ValueError:
        # Not JSON at all (a plain-text answer): return it as the response verbatim.
        return {
            "response": json_resp,
            "apis": []
        }
    return {
        "response": json_object.get("response", ""),
        "apis": json_object.get("apis", [])
    }


@api.post("/marketplace-assistant", status_code=201)
async def marketplace_assistant(request: Query, keyID: str, x_jwt_assertion: str = Header(None)):
    response = await generate_response(user_roles=request.user_roles, tenant_domain=request.tenant_domain, message=request.query,
                                       history=request.history, partitionID=keyID, auth_token=x_jwt_assertion)
    return response


@api.get("/health")
def health():
    """Check the api is running"""
    return {"status": "Running"}
