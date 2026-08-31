# Spec Populator Service

Indexes API definitions in the vector store used by Marketplace Assistant.

# Deployment

## Prerequisites

Use Python 3.9 or later. From this directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuring the Spec Populator Service

Create a `.env` file with the Azure OpenAI embedding and Milvus settings:

```dotenv
# Azure OpenAI creates embeddings from API definitions.
AZURE_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_DEPLOYMENT=

# Milvus stores the API vectors used by Marketplace Assistant.
MILVERSE_URL=
MILVERSE_API_KEY=
COLLECTION_NAME=
```

This service reads its settings from the process environment, so export these values (or load the
`.env` file) in the shell that starts the service.

### Switching the AI model

This service uses an **embedding** model to turn API definitions into vectors. To use a
**different provider** (OpenAI, Anthropic, Bedrock, a self-hosted model, and so on), a code change
is required — the embedding client is constructed directly rather than selected by configuration:

1. In [utils.py](utils.py), replace the `AzureOpenAIEmbeddings` client returned by
   `get_emb_model()` with the embeddings client for your provider.
2. Add that provider's package to [requirements.txt](requirements.txt) if it is not already present.
3. Replace the `AZURE_*` variables in `.env` with the ones your provider requires, and read them in
   `utils.py`.

**The embedding model must match the one used by `marketplace-assistant-api`.** Records indexed with
one embedding model cannot be searched reliably with another, so if you change the embedding model
after APIs have been indexed, re-index them.

# Build and Run

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Accessing the Service

It is available at `http://localhost:8000`.

Use the same Milvus collection, embedding deployment, and `keyID` as Marketplace Assistant. The API operations and request schemas are in [openapi.yaml](openapi.yaml).
