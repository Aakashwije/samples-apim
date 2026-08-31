# API Design Assistant

AI-based tool for designing APIs through natural language commands.

# Deployment
Follow these steps to set up the API Design Assistant service locally.

## Prerequisites

Use Python 3.11 or later. From this directory, create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuring the API Design Assistant Service

Create a `.env` file with your Azure OpenAI and Redis connection details:

```dotenv
# Azure OpenAI is used to generate and refine API specifications.
AZURE_OPENAI_API_KEY=
AZURE_ENDPOINT=
AZURE_CHAT_DEPLOYMENT=
AZURE_CHAT_VERSION=

# Redis stores conversation state for each sessionId.
REDIS_HOST=
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=
```

The current Redis client uses TLS, so point these settings to a TLS-enabled Redis instance.

### Switching the AI model

To use a **different provider** (OpenAI, Anthropic, Bedrock, a self-hosted model, and so on), a code
change is required — the provider client is constructed directly rather than selected by
configuration:

1. In [config.py](config.py), replace the `AzureChatOpenAI` client returned by `get_llm()` with the
   client for your provider — for example `ChatOpenAI` from `langchain_openai`, or the equivalent
   LangChain integration for another provider.
2. Add that provider's package to [requirements.txt](requirements.txt) if it is not already present.
3. Replace the `AZURE_*` variables in `.env` with the ones your provider requires, and read them in
   `config.py`.

The rest of the service is provider-agnostic: prompts, session handling, and the response contract
do not change.

# Run

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Accessing the Service

The service is available at `http://localhost:8000`. The API contract is in [openapi.yaml](openapi.yaml).

## Example Request

```bash
curl -X POST 'http://localhost:8000/chat' \
  -H 'Content-Type: application/json' \
  -d '{"text":"Create an API for a banking transaction.","sessionId":"local-test"}'
```
