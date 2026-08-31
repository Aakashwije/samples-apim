# Marketplace Assistant API

Answers questions about APIs indexed in the shared vector store.

# Deployment

## Prerequisites

Use Python 3.9 or later. From this directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt
```

### Configuring the Marketplace Assistant API

Create a `.env` file with the Azure OpenAI and vector-store settings:

```dotenv
# Azure OpenAI generates answers and embeddings for API discovery.
AZURE_OPENAI_API_KEY=
AZURE_ENDPOINT=
AZURE_CHAT_DEPLOYMENT=
AZURE_CHAT_VERSION=
AZURE_EMBEDDING_DEPLOYMENT=

# Zilliz Cloud is the vector store used to search indexed APIs.
ZILLIZ_CLOUD_URI=
ZILLIZ_CLOUD_API_KEY=
COLLECTION_NAME=
```

### Switching the AI models

This service uses two models: a **chat** model to generate answers and an **embedding** model to
search indexed APIs. To use a **different provider** (OpenAI, Anthropic, Bedrock, a self-hosted
model, and so on), a code change is required — the provider clients are constructed directly rather
than selected by configuration:

1. In [app/api.py](app/api.py), replace the `AzureChatOpenAI` client returned by `get_llm()` **and**
   the `AzureAIEmbeddingsModel` returned by `get_embeddings()` with the equivalents for your
   provider. Both must be changed — chat and embeddings are separate clients.
2. Add that provider's package to [app/requirements.txt](app/requirements.txt) if it is not already
   present.
3. Replace the `AZURE_*` variables in `.env` with the ones your provider requires, and read them in
   [app/constants.py](app/constants.py).

**The embedding model must match the one used by `spec_populator_service`.** Records indexed with
one embedding model cannot be searched reliably with another, so if you change the embedding model
after APIs have been indexed, re-index them.

The rest of the service is provider-agnostic: prompts, retrieval logic, and the response contract do
not change.

# Build and Run

Start the service:

```bash
uvicorn app.api:api --host 0.0.0.0 --port 8000 --reload
```

## Accessing the Service

It is available at `http://localhost:8000`. The vector store must contain records created with the same `keyID` used for chat requests. See [openapi.yaml](openapi.yaml) for the request format.

## Example Request

```bash
curl -X POST 'http://localhost:8000/marketplace-assistant?keyID=local-key' \
  -H 'Content-Type: application/json' \
  -d '{"query":"What APIs are available?","history":[],"tenant_domain":"carbon.super","user_roles":"[]"}'
```
