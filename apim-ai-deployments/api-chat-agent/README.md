# API Chat Agent

Prepares REST API definitions and executes API test steps from natural-language commands.

# Deployment

## Prerequisites

Install Ballerina 2201.8.4 or a compatible update.

### Configuring the API Chat Agent

Create `Config.toml` in this directory:

```toml
# Azure OpenAI generates API descriptions, sample queries, and test steps.
azureOpenAIToken = ""
azureOpenAIServiceUrl = "https://<your-resource>.openai.azure.com/openai"
azureOpenAIDeploymentId = ""
AZURE_OPENAI_API_VERSION = ""

# Redis caches enriched API definitions and in-progress test cases.
redisHost = ""
redisPassword = ""

```

### Using a provider other than Azure OpenAI

The reference implementation is written against Azure OpenAI, so **a different provider requires a
code change** — the model client is constructed directly rather than selected by configuration.
To switch:

1. In [agent.bal](agent.bal), replace the `agent:AzureChatGptModel` created by `initializeModel()`
   with the model type for your provider. The `wso2/ai.agent` package also ships
   `agent:ChatGptModel` for non-Azure OpenAI; other providers need an equivalent client.
2. Update the `model` declaration in the same file to that type.
3. Replace the `azureOpenAI*` configurables in [service.bal](service.bal) with the values your
   provider requires, and set them in `Config.toml`.

Whichever model you use, it must support **function calling** as well as chat completion — API Chat
relies on function calling to select which API resource to invoke.

# Build and Run

```bash
bal run
```

The service listens on `http://localhost:9090`. The supported endpoints are described in
[openapi.yaml](openapi.yaml).

