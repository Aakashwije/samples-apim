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
import ballerina/file;
import ballerina/http;
import ballerina/io;
import ballerina/lang.regexp;
import ballerina/test;
import wso2/ai.agent;

const string SPECIFICATIONS_DIRECTORY = "tests/resources/specifications";
const string PARSED_SPECIFICATIONS_DIRECTORY = "tests/resources/parsed_specifications";
const string EXTRACTED_SPECIFICATIONS_DIRECTORY = "tests/resources/extracted_specifications";

string serviceURL = "http://localhost:9090";
http:Client serviceClient = check new (serviceURL);

@test:Config {
    groups: ["logic"]
}
function parseOpenApiSpecTest() returns error? {
    file:MetaData[] directory = check file:readDir(SPECIFICATIONS_DIRECTORY);
    foreach file:MetaData file in directory {
        string filename = regexp:split(re `/`, file.absPath).pop();
        string parsedSpecPath = string `${PARSED_SPECIFICATIONS_DIRECTORY}/${filename}`;
        map<json> openApiSpec = check io:fileReadJson(file.absPath).ensureType();
        map<json> openApiSpecParsed = check io:fileReadJson(parsedSpecPath).ensureType();
        test:assertEquals(agent:parseOpenApiSpec(openApiSpec), openApiSpecParsed);
    }
}

@test:Config {
    groups: ["logic"]
}
function extractToolsFromOpenApiJsonSpecTest() returns error? {
    file:MetaData[] directory = check file:readDir(PARSED_SPECIFICATIONS_DIRECTORY);
    foreach file:MetaData file in directory {
        string filename = regexp:split(re `/`, file.absPath).pop();
        string extractedSpecPath = string `${EXTRACTED_SPECIFICATIONS_DIRECTORY}/${filename}`;
        map<json> openApiSpecParsed = check io:fileReadJson(file.absPath).ensureType();
        map<json> openApiSpecExtracted = check io:fileReadJson(extractedSpecPath).ensureType();
        test:assertEquals(agent:extractToolsFromOpenApiJsonSpec(openApiSpecParsed), openApiSpecExtracted);
    }
}

// One resource the agent selected, paired with the output the harness obtained by
// invoking it. Only the tests need this pairing: the service's `/chat` returns the
// resource alone and never invokes the API under test itself.
type ExecutionResult record {|
    ApiResourceDefinition 'resource;
    agent:HttpOutput output;
|};

// Test-local view of a single client-invoked step. `/chat` returns only the
// resource the client should invoke (`TestExecutionOnPremResponse`); the harness
// invokes the mock itself to obtain the output, then reassembles the old
// {resource, output} shape so the accuracy assertors keep working unchanged.
type TestExecutionResponse record {|
    IN_PROGRESS|TERMINATED taskStatus;
    ExecutionResult result;
|};

// to store execution and completion responses for each test case.
type TestResponse record {|
    COMPLETED|TERMINATED|ERROR terminationCause;
    TestExecutionResponse[] executionResponseList;
    string completionResponseResult?;
|};

// `/chat` correlates session state by this header.
map<string> header = {
    "apiChatRequestId": "123"
};

// Invoke the currently selected mock service for the resource the agent chose,
// mirroring what the agent's toolkit would have done in the self-invoking flow.
function invokeMock(ApiResourceDefinition apiResource) returns agent:HttpOutput|error {
    isolated function (HttpInput) returns (agent:HttpOutput|error) caller;
    lock {
        caller = <isolated function (HttpInput) returns (agent:HttpOutput|error)>mockResource;
    }
    HttpInput httpInput = {path: apiResource.path};
    map<json>? inputs = apiResource.inputs;
    if inputs is map<json> {
        json params = inputs["parameters"];
        if params is map<json> {
            httpInput.parameters = params;
        }
        json requestBody = inputs["requestBody"];
        if requestBody is map<json> {
            httpInput.requestBody = requestBody;
        }
    }
    return caller(httpInput);
}

// Drive a full session against the client-invoked `/chat` resource: send the
// command, then for every returned resource invoke the mock and report the
// result back, until the agent completes or the session terminates.
function getTestResponse(string query, agent:HttpTool[] tools) returns TestResponse|ErrorInfo|error {

    TestExecutionResponse[] executionResponses = [];

    TestInitializationRequest initializationRequest = {
        command: query,
        apiSpec: {
            serviceUrl: "http://localhost:8080",
            tools
        }
    };

    TestExecutionOnPremResponse|TestCompletionOnPremResponse firstResponse =
        check serviceClient->/chat.post(initializationRequest, headers = header);

    if firstResponse is TestCompletionOnPremResponse {
        return {
            terminationCause: COMPLETED,
            executionResponseList: executionResponses,
            completionResponseResult: firstResponse.result
        };
    }

    agent:HttpOutput output = check invokeMock(firstResponse.'resource);
    executionResponses.push({
        taskStatus: firstResponse.taskStatus,
        result: {'resource: firstResponse.'resource, output}
    });
    if output.path == "/" {
        return {
            terminationCause: ERROR,
            executionResponseList: executionResponses
        };
    }
    if firstResponse.taskStatus == TERMINATED {
        return {
            terminationCause: TERMINATED,
            executionResponseList: executionResponses
        };
    }

    while true {
        TestExecutionResultRequest resultRequest = {response: output};
        TestExecutionOnPremResponse|TestCompletionOnPremResponse response =
            check serviceClient->/chat.post(resultRequest, headers = header);

        if response is TestCompletionOnPremResponse {
            // break the loop when we get the completion response.
            return {
                terminationCause: COMPLETED,
                executionResponseList: executionResponses,
                completionResponseResult: response.result
            };
        }

        output = check invokeMock(response.'resource);
        executionResponses.push({
            taskStatus: response.taskStatus,
            result: {'resource: response.'resource, output}
        });

        if output.path == "/" {
            return {
                terminationCause: ERROR,
                executionResponseList: executionResponses
            };
        }
        if response.taskStatus == TERMINATED {
            // break the loop when we get the termination response.
            return {
                terminationCause: TERMINATED,
                executionResponseList: executionResponses
            };
        }
    }
}

//expected execution Response for validPayloadTest test case.
ExecutionResult getUserResult = {
    'resource: {
        method: "GET",
        path: "/user/{username}",
        inputs: {"parameters": {"username": "Bob_123"}}
    },
    output: {
        code: 200,
        path: "/user/Bob_123",
        headers: {contentType: "application/json"},
        body: [
            {
                "id": 1,
                "username": "Bob_123",
                "firstName": "Bob",
                "lastName": "Johnson",
                "email": "bob@gmail.com",
                "password": "XXXXXXXXXXX",
                "phone": "123-456-7890",
                "userStatus": 1
            }
        ]
    }
};

TestExecutionResponse expectedGetUserResponse = {
    taskStatus: IN_PROGRESS,
    result: getUserResult
};

//test case for the correct TestInitializationRequest and TestExecutionResultRequest.
@test:Config {
    groups: ["logic"]
}
function validPayloadTest() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }

    TestResponse|ErrorInfo|error testResponse = getTestResponse("Get user with username Bob_123", petStoreTools);
    if testResponse is error {
        test:assertFail(msg = string `Error occurred while retrieving the response : ${testResponse.toString()}`);
    }

    if testResponse is ErrorInfo {
        test:assertFail(msg = string `Error message:${testResponse.detail}`);
    }
    boolean isExpectedResponseReceived = false;
    if testResponse.executionResponseList[0] == expectedGetUserResponse {
        isExpectedResponseReceived = true;
    }
    test:assertTrue(isExpectedResponseReceived, msg = "The expected response is not included in the TestExecutionResponse list");
    test:assertEquals(testResponse.terminationCause, COMPLETED);
    test:assertEquals(testResponse.completionResponseResult, "The user with username \"Bob_123\" is Bob Johnson.");
}

//test case to test when there is an empty command.
@test:Config {
    groups: ["logic"]
}
function testEmptyCommand() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }

    TestResponse|ErrorInfo|error response = getTestResponse("", petStoreTools);

    if response is TestResponse {
        test:assertFail(msg = "Cannot receive a TestResponse for an empty command.");
    }
    if response is ErrorInfo {
        test:assertFail(msg = "Cannot receive an ErrorInfo for an empty command.");
    }
    test:assertEquals(response.detail().toArray()[0], 500);
    test:assertEquals(response.detail().toArray()[2], {"level": "WARN", "detail": "Invalid query is provided.", "code": "INVALID_COMMAND"});
}

//test when the payload has an invalid initialization request.
@test:Config {
    groups: ["logic"]
}
function testInvalidInitializationRequest() returns error? {
    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }

    TestExecutionOnPremResponse|ErrorInfo|http:ClientError response = serviceClient->/chat.post("invalidInitializationRequest", headers = header);

    if response is TestExecutionOnPremResponse {
        test:assertFail(msg = "cannot receive a TestExecutionOnPremResponse for an invalid initialization request.");
    }
    if response is ErrorInfo {
        test:assertFail(msg = "cannot receive an ErrorInfo for an invalid initialization request.");
    }
    test:assertEquals(response.detail().toArray()[0], 400);
    test:assertEquals(response.message(), "Bad Request");
}

//expected execution result for maxIterationTest test case.
ExecutionResult getPet = {
    'resource: {
        method: "GET",
        path: "/pet/getPet/{petId}",
        inputs: {"parameters": {"petId": 5}}
    },
    output: {
        code: 200,
        path: "/pet/getPet/5",
        headers: {contentType: "application/json"},
        body:
            {
            "id": 5,
            "name": "Fluffy",
            "category": {
                "id": 1,
                "name": "Domestic"
            },
            "photoUrls": [
                "https://example.com/fluffy.jpg"
            ],
            "tags": [
                {
                    "id": 101,
                    "name": "Cute"
                }
            ],
            "status": "available"
        }
    }
};

//test case to check when it reaches maximum iterations.
@test:Config {
    groups: ["logic"]
}
function maxIterationTest() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }
    TestResponse|ErrorInfo|error testResponse = getTestResponse("Get pet with ID 5", petStoreTools);

    if testResponse is error {
        test:assertFail(msg = string `An error occurred while retrieving the response for maxIterationTest: ${testResponse.toString()}`);
    }

    if testResponse is ErrorInfo {
        test:assertFail(msg = string `Error message:${testResponse.detail}`);
    }
    if testResponse.terminationCause == COMPLETED {
        test:assertFail(msg = "Cannot recieve a completion response for maxIterationTest");
    }
    TestExecutionResponse lastResponse = testResponse.executionResponseList.pop();
    test:assertEquals(testResponse.terminationCause, TERMINATED);
    test:assertEquals(lastResponse.result, getPet);
}

//test case to test when the LLM sends an invalid response.
@test:Config {
    groups: ["logic"]
}
function invalidLLMResponseTest() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }
    TestResponse|ErrorInfo|error testResponse = getTestResponse("Delete pet 1", petStoreTools);

    if testResponse is TestResponse {
        test:assertFail(msg = "Cannot receive a TestResponse for an invalid LLM response.");
    }

    if testResponse is ErrorInfo {
        test:assertFail(msg = "Cannot receive an ErrorInfo for an invalid LLM response.");
    }
    test:assertEquals(testResponse.detail().toArray()[0], 500);
    test:assertEquals(testResponse.detail().toArray()[2], {"level": "ERROR", "detail": "An error occurred during query execution. Try again.", "code": "LLM"});
}

//test case for to test when the initialization request has an invalid service url.
@test:Config {
    groups: ["logic"]
}
function emptyServiceUrlTest() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }

    TestInitializationRequest initializationRequest = {
        command: "List available pets",
        apiSpec: {
            tools: petStoreTools
        }
    };

    TestExecutionOnPremResponse|ErrorInfo|error response = serviceClient->/chat.post(initializationRequest, headers = header);

    if response is TestExecutionOnPremResponse {
        test:assertFail(msg = "cannot receive a TestExecutionOnPremResponse for an empty service url.");
    }

    if response is ErrorInfo {
        test:assertFail(msg = "cannot receive an ErrorInfo for an empty service url.");
    }
    test:assertEquals(response.detail().toArray()[0], 500);
    test:assertEquals(response.detail().toArray()[2], {"level": "WARN", "detail": "The specification could not be parsed. Ensure you are using a valid specification.", "code": "INVALID_SPECIFICATION"});
}

//expected executionResponse for invokeAllTest test case.
TestExecutionResponse[] expectedExecutionResponse = [{"taskStatus": "IN_PROGRESS", "result": {"resource": {"method": "GET", "path": "/books", "inputs": {}}, "output": {"code": 200, "path": "/books", "headers": {"contentType": "application/json"}, "body": {"value": ["The Lord of the Rings", "Harry Potter", "Brave New World"]}}}}, {"taskStatus": "IN_PROGRESS", "result": {"resource": {"method": "DELETE", "path": "/books/{id}", "inputs": {"parameters": {"id": "12345"}}}, "output": {"code": 200, "path": "/books/12345", "headers": {"contentType": "application/json"}, "body": {"value": "The book has been deleted successfully."}}}}];

//test case to test when the command is to invoke all resources.
@test:Config {
    groups: ["logic"]
}
function invokeAllTest() returns error? {

    isolated function readingList = mockReadingList;
    lock {
        mockResource = readingList;
    }
    agent:HttpTool[] tools = [
        {
            "name": "GET-books",
            "description": "Returns a list of all books.. This tool invokes a HTTP GET resource",
            "method": "GET",
            "path": "/books"
        },
        {
            "name": "DELETE-books_id",
            "description": "Deletes a book with the specified ID.. This tool invokes a HTTP DELETE resource",
            "method": "DELETE",
            "path": "/books/{id}",
            "parameters": {
                "id": {
                    "location": "path",
                    "description": "id of book to delete",
                    "required": true,
                    "schema": {
                        "type": "string"
                    }
                }
            }
        }
    ];

    TestResponse|ErrorInfo|error testResponse = getTestResponse("invoke all resources", tools);

    if testResponse is error {
        test:assertFail(msg = string `Error occurred while retrieving the response : ${testResponse.toString()}`);
    }

    if testResponse is ErrorInfo {
        test:assertFail(msg = string `Error message:${testResponse.detail}`);
    }
    //all the expected responses in the expectedExecutionResponse should be received.
    if testResponse.terminationCause == COMPLETED {
        test:assertEquals(testResponse.completionResponseResult, "All 2 resources were invoked.", msg = "Incorrect completion response was received for invokeAllTest");
    } else {
        test:assertFail(msg = "Cannot recieve a completion response for invokeAllTest");
    }

    boolean isAllExpectedResponsesReceived = false;
    if testResponse.executionResponseList == expectedExecutionResponse {
        isAllExpectedResponsesReceived = true;
    }
    test:assertTrue(isAllExpectedResponsesReceived, msg = "All the expected responses were not received.");
}

//test case to test when there is a connection issue. The LLM connection error is
// now returned as a handled 500 (previously it was mistakenly returned as a 201),
// so it surfaces to the client as an error carrying the ErrorInfo body.
@test:Config {
    groups: ["logic"]
}
function llmConnectionErrorTest() returns error? {

    isolated function mockPetstore = mockPetStore;
    lock {
        mockResource = mockPetstore;
    }
    TestResponse|ErrorInfo|error testResponse = getTestResponse("Find all available pets", petStoreTools);

    if testResponse is TestResponse {
        test:assertFail(msg = "Cannot receive a TestResponse for a connection error.");
    }

    if testResponse is ErrorInfo {
        test:assertFail(msg = "A connection error must be returned as a 500, not as a 201 ErrorInfo.");
    }
    test:assertEquals(testResponse.detail().toArray()[0], 500);
    test:assertEquals(testResponse.detail().toArray()[2], {"level": "WARN", "detail": "There was an error connecting to Azure OpenAI.", "code": "LLM_CONNECTION"});
}
