// Copyright (c) 2026, WSO2 LLC. (https://www.wso2.com).
//
// WSO2 LLC. licenses this file to you under the Apache License,
// Version 2.0 (the "License"); you may not use this file except
// in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied. See the License for the
// specific language governing permissions and limitations
// under the License.
import ballerina/lang.regexp;
import ballerina/lang.runtime;
import ballerina/log;
import wso2/ai.agent;

function enrichSpecification(string trackingId, map<json> openApi) returns record {|map<json> openApiSpec; SampleQuery[] queries;|}|error {
    agent:OpenApiSpec openApiSpec;
    agent:Paths? paths;
    final ApiResource[] & readonly resources;
    final map<agent:Schema|agent:Reference>? & readonly schemas;
    do {
        openApiSpec = check agent:parseOpenApiSpec(openApi);
        ApiResourceVisitor resourceVisitor = new;
        check resourceVisitor.visitOpenAPISpec(openApiSpec);
        resources = resourceVisitor.resources.cloneReadOnly();
        schemas = resourceVisitor.schemas.cloneReadOnly();
        paths = openApiSpec.paths;
    } on fail error e {
        return error InvalidSpecificationError("Failed to parse the OpenAPI specification.", e);
    }
    if paths == () {
        return error InvalidSpecificationError("Failed to find resources in the OpenAPI specification.");
    }

    fork {
        worker descriptionCreator returns ApiResourceDescriptor[]|error {
            return generateDescriptions(trackingId, resources, schemas);
        }
        worker queryCreator returns GeneratedQuerySet|error {
            return generateSampleQuery(trackingId, resources, schemas);
        }
    }

    record {|
        ApiResourceDescriptor[]|error descriptionCreator;
        GeneratedQuerySet|error queryCreator;
    |} results = wait {descriptionCreator, queryCreator};

    ApiResourceDescriptor[]|error enrichmentResult = results.descriptionCreator;
    GeneratedQuerySet|error queryResult = results.queryCreator;

    ApiResourceDescriptor[] resourceDescriptions = [];
    if enrichmentResult is error {
        foreach ApiResource apiResource in resources {
            string? description = apiResource.spec.description ?: apiResource.spec.summary;
            if description is () {
                return enrichmentResult;
            }
            resourceDescriptions.push({
                path: apiResource.path,
                method: apiResource.method,
                description
            });
        }
    } else {
        resourceDescriptions = enrichmentResult;
    }

    GeneratedQuerySet generatedQuery;
    if queryResult is error {
        generatedQuery = check generateSampleQuery(trackingId, resourceDescriptions);
    } else {
        generatedQuery = queryResult;
    }

    foreach ApiResourceDescriptor item in resourceDescriptions {
        if !paths.hasKey(item.path) {
            return error("Failed to find the operation for the resource", path = item.path);
        }
        agent:Operation operation = check paths.get(item.path)[item.method.toLowerAscii()].ensureType();
        // create a valid name for the tool
        string operationId = string `${item.method}-${regexp:replaceAll(re `^[/{]+|[/}]+$`, item.path, "")}`;
        operation.operationId = regexp:replaceAll(re `[^a-zA-Z0-9_-]+`, operationId, "_");

        operation.description = item.description + string `. This tool invokes a HTTP ${item.method} resource`;
    }
    SampleQuery[] sampleQueries = [
        {scenario: "Invoke all resources of the API", query: INVOKE_ALL_RESOURCES_COMMAND},
        {scenario: "Invoke a single resource of the API", query: generatedQuery.singleResourceCall}
    ];
    if resources.length() > 1 {
        sampleQueries.push({scenario: "Invoke an action involving multiple resources", query: generatedQuery.multiResourceCall});
    }
    return {
        openApiSpec: check openApiSpec.cloneWithType(),
        queries: sampleQueries
    };
}

isolated function generateTextWithLlm(string prompt) returns string|LlmTokenLimitExceededError|agent:LlmError {
    agent:ChatMessage[] messages = [
        {
            role: "user",
            content: prompt
        }
    ];
    return generateTextWithChatLlm(messages);
}

isolated function generateTextWithChatLlm(agent:ChatMessage[] messages) returns string|LlmTokenLimitExceededError|agent:LlmError {
    string|agent:LlmError generatedText = model.chatComplete(messages, stop = ());
    if generatedText is error {
        return error agent:LlmConnectionError("Failed to connect to the OpenAI API.", handleLlmGenerationErrors(generatedText));
    }
    return generatedText;
}

# Strips a leading/trailing markdown code fence (```json ... ```) from an LLM
# response, so JSON wrapped in a fence still parses. Plain JSON is returned unchanged.
#
# + text - the raw LLM output
# + return - the JSON body without any surrounding code fence
isolated function stripCodeFence(string text) returns string {
    string trimmed = text.trim();
    if !trimmed.startsWith("```") {
        return trimmed;
    }
    int? newlineIndex = trimmed.indexOf("\n");
    string body = newlineIndex is int ? trimmed.substring(newlineIndex + 1) : trimmed;
    if body.endsWith("```") {
        body = body.substring(0, body.length() - 3);
    }
    return body.trim();
}

isolated function generateDescriptions(string trackingId, ApiResource[] resources, map<agent:Schema|agent:Reference>? schemas) returns ApiResourceDescriptor[]|LlmTokenLimitExceededError|agent:LlmError {
    string prompt = generateEnrichmentPrompt(resources, schemas);
    string strEnrichedResourceSpecs = check generateTextWithLlm(prompt);

    log:printDebug("Description generation was successful.", id = trackingId, enrichedApiSpec = strEnrichedResourceSpecs);
    ApiResourceDescriptor[]|error enrichedResourceSpecs = stripCodeFence(strEnrichedResourceSpecs).fromJsonStringWithType();
    if enrichedResourceSpecs is error {
        return error agent:LlmInvalidGenerationError("Generated descriptions does not follow expected format", handleLlmGenerationErrors(enrichedResourceSpecs));
    }
    return enrichedResourceSpecs;
}

isolated function generateSampleQuery(string trackingId, ApiResource[]|ApiResourceDescriptor[] resources, map<agent:Schema|agent:Reference>? schemas = ()) returns GeneratedQuerySet|LlmTokenLimitExceededError|agent:LlmError {
    string prompt = generateQueryGenerationPrompt(resources, schemas);
    string strGeneratedQueries = check generateTextWithLlm(prompt);

    log:printDebug("Query generation was successful", id = trackingId, query = strGeneratedQueries);
    GeneratedQuerySet|error queries = stripCodeFence(strGeneratedQueries).fromJsonStringWithType();
    if queries is error {
        return error agent:LlmInvalidGenerationError("Generated queries does not follow expected format", handleLlmGenerationErrors(queries));
    }
    return queries;
}

class ApiResourceVisitor {
    ApiResource[] resources = [];
    map<agent:Schema|agent:Reference>? schemas = {};
    agent:Paths? paths = {};
    map<agent:PathItem|agent:Reference> pathItems = {};

    isolated function visitOpenAPISpec(agent:OpenApiSpec openApiSpec) returns error? {
        self.schemas = openApiSpec.components?.schemas;
        self.pathItems = openApiSpec.components?.pathItems ?: {};
        self.paths = openApiSpec.paths;
        check self.visitPaths(openApiSpec.paths);
    }

    isolated function visitPaths(agent:Paths? paths) returns error? {
        if paths == () {
            return;
        }

        foreach [string, agent:PathItem|agent:Reference] [path, pathItem] in paths.entries() {
            agent:PathItem|agent:Reference resolvedPathItem = pathItem;
            while resolvedPathItem is agent:Reference {
                if !self.pathItems.hasKey(resolvedPathItem.\$ref) {
                    return error InvalidResourcePathError("The OpenAPI specification includes path references that are not defined.");
                }
                resolvedPathItem = self.pathItems.get(resolvedPathItem.\$ref);
            }
            if path.includes("/*") {
                return error InvalidResourcePathError("The OpenAPI specification includes wildcard path definitions that are not supported. Ensure that the specification does not contain wildcard paths.");
            }
            if path == "" {
                return error InvalidResourcePathError("The OpenAPI specification includes empty path definitions that are not supported. Ensure that the specification contains valid path definitions.");
            }
            if resolvedPathItem !is agent:PathItem {
                return error InvalidResourcePathError("The OpenAPI specification includes path references that are not supported. Ensure that the specification does not contain path references.");
            }
            self.visitPathItem(path, resolvedPathItem);
        }
    }

    isolated function visitPathItem(string path, agent:PathItem pathItem) {
        self.visitOperations(path, agent:GET, pathItem.get);
        self.visitOperations(path, agent:POST, pathItem.post);
        self.visitOperations(path, agent:PUT, pathItem.put);
        self.visitOperations(path, agent:DELETE, pathItem.delete);
        self.visitOperations(path, agent:OPTIONS, pathItem.options);
        self.visitOperations(path, agent:HEAD, pathItem.head);
        self.visitOperations(path, agent:PATCH, pathItem.patch);
    }

    isolated function visitOperations(string path, string method, agent:Operation? operation) {
        if operation == () {
            return;
        }
        ApiResource httpResource = {
            path,
            method,
            spec: operation.cloneReadOnly()
        };
        self.resources.push(httpResource);
    }
}

isolated function generateEnrichmentPrompt(ApiResource[] resources, map<agent:Schema|agent:Reference>? schemas) returns string {
    string[] resourceDescriptions = resources.map(rss => string `[${rss.method}]${rss.path}: ${rss.spec.toString()}`);
    return string `You are a technical writer who can understand the following HTTP resource definitions extracted from an Open API specification. You are supposed to write a short description for them with 1-2 sentences or improve the existing description by adding more details.

The HTTP resource definitions are as follows:
${string:'join("\n", ...resourceDescriptions)}

Also, you can make use of the following schemas to understand the references in the Open API specification.
${schemas.toString()}

The answer should ALWAYS be provided as an array of JSONs in the following format:
[{
    "path": {{Include the path to the resource}}
    "method": {{Include the HTTP method of the resource}}
    "description": {{Generate a meaningful description for the resource by looking at the given information}}
}]`;
}

isolated function generateQueryGenerationPrompt(ApiResource[]|ApiResourceDescriptor[] resources, map<agent:Schema|agent:Reference>? schemas) returns string {
    string[] resourceDescriptions = resources.map(rss => string `[${rss.method}]${rss.path}: ${rss is ApiResource ? rss.spec.toString() : rss.description}`);
    return string `You are a technical writer who can understand the following HTTP resource definitions extracted from an Open API specification. You are supposed to write sample natural language queries for a task that can be executed by calling TWO OR MORE HTTP resources of the API. 

The HTTP resource definitions are as follows:
${string:'join("\n", ...resourceDescriptions)}

${schemas is () ? "" : string `Also, you can make use of the following schemas to understand the references in the Open API specification.
${schemas.toString()}
`}
Make sure to write only TWO queries as expected by the JSON format given below. But DO NOT mention which resources are required to execute the task. Use specific example values for the input parameters and payloads of the resources. The response should be the natural language query, and nothing more.

The answer should ALWAYS be provided as an JSONs in the following format:
{
    "singleResourceCall": {{Sample natural language query that require executing only a single API resource selected from the above.}}
    "multiResourceCall": {{Sample natural language query that must execute at least two API resources selected from the above.}}
}`;
}

public class RetryManager {
    private int count;
    private int initialRetryCount = 3;
    private decimal initialDelay = 1; // Initial delay in seconds
    private decimal maxDelay = 16; // Maximum delay in seconds
    public function init(int count = 3) {
        self.count = count;
        self.initialRetryCount = count;
    }
    public function shouldRetry(error e) returns boolean {
        error? cause = e.cause();
        if cause is LlmTokenLimitExceededError|LlmContentPolicyViolationError {
            return false;
        }
        if self.count > 0 {
            self.count -= 1;
            decimal delaySec = self.calculateBackoffDelay();
            log:printInfo(string `Retry attempt after a delay of ${delaySec.toString()} seconds. Remaining retries: ${self.count}`, e);
            runtime:sleep(delaySec);
            return true;
        } else {
            return false;
        }
    }

    private function calculateBackoffDelay() returns decimal {
        return decimal:min(self.initialDelay * <decimal>float:pow(2, <float>(self.initialRetryCount - self.count)), self.maxDelay);
    }
}
