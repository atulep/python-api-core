# Copyright 2014 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import http.client
import json
from google.rpc import status_pb2
from google.rpc.status_pb2 import Status

import grpc
import mock
import requests
from google.rpc import error_details_pb2
from google.rpc import code_pb2
from google.protobuf import any_pb2, json_format
from grpc_status import rpc_status
from google.api_core import exceptions
from google.protobuf import text_format

def test_create_google_cloud_error():
    exception = exceptions.GoogleAPICallError("Testing")
    exception.code = 600
    assert str(exception) == "600 Testing []"
    assert exception.message == "Testing"
    assert exception.errors == []
    assert exception.response is None


def test_create_google_cloud_error_with_args():
    error = {
        "code": 600,
        "message": "Testing",
    }
    response = mock.sentinel.response
    exception = exceptions.GoogleAPICallError("Testing", [error], response=response)
    exception.code = 600
    assert str(exception) == "600 Testing []"
    assert exception.message == "Testing"
    assert exception.errors == [error]
    assert exception.response == response


def test_from_http_status():
    message = "message"
    exception = exceptions.from_http_status(http.client.NOT_FOUND, message)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == message
    assert exception.errors == []


def test_from_http_status_with_errors_and_response():
    message = "message"
    errors = ["1", "2"]
    response = mock.sentinel.response
    exception = exceptions.from_http_status(
        http.client.NOT_FOUND, message, errors=errors, response=response
    )

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == message
    assert exception.errors == errors
    assert exception.response == response


def test_from_http_status_unknown_code():
    message = "message"
    status_code = 156
    exception = exceptions.from_http_status(status_code, message)
    assert exception.code == status_code
    assert exception.message == message


def make_response(content):
    response = requests.Response()
    response._content = content
    response.status_code = http.client.NOT_FOUND
    response.request = requests.Request(
        method="POST", url="https://example.com"
    ).prepare()
    return response


def test_from_http_response_no_content():
    response = make_response(None)

    exception = exceptions.from_http_response(response)

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == "POST https://example.com/: unknown error"
    assert exception.response == response


def test_from_http_response_text_content():
    response = make_response(b"message")
    response.encoding = "UTF8"  # suppress charset_normalizer warning

    exception = exceptions.from_http_response(response)

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == "POST https://example.com/: message"


def test_from_http_response_json_content():
    response = make_response(
        json.dumps({"error": {"message": "json message", "errors": ["1", "2"]}}).encode(
            "utf-8"
        )
    )

    exception = exceptions.from_http_response(response)

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == "POST https://example.com/: json message"
    assert exception.errors == ["1", "2"]


def test_from_http_response_bad_json_content():
    response = make_response(json.dumps({"meep": "moop"}).encode("utf-8"))

    exception = exceptions.from_http_response(response)

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == "POST https://example.com/: unknown error"


def test_from_http_response_json_unicode_content():
    response = make_response(
        json.dumps(
            {"error": {"message": "\u2019 message", "errors": ["1", "2"]}}
        ).encode("utf-8")
    )

    exception = exceptions.from_http_response(response)

    assert isinstance(exception, exceptions.NotFound)
    assert exception.code == http.client.NOT_FOUND
    assert exception.message == "POST https://example.com/: \u2019 message"
    assert exception.errors == ["1", "2"]


def test_from_grpc_status():
    message = "message"
    exception = exceptions.from_grpc_status(grpc.StatusCode.OUT_OF_RANGE, message)
    assert isinstance(exception, exceptions.BadRequest)
    assert isinstance(exception, exceptions.OutOfRange)
    assert exception.code == http.client.BAD_REQUEST
    assert exception.grpc_status_code == grpc.StatusCode.OUT_OF_RANGE
    assert exception.message == message
    assert exception.errors == []


def test_from_grpc_status_as_int():
    message = "message"
    exception = exceptions.from_grpc_status(11, message)
    assert isinstance(exception, exceptions.BadRequest)
    assert isinstance(exception, exceptions.OutOfRange)
    assert exception.code == http.client.BAD_REQUEST
    assert exception.grpc_status_code == grpc.StatusCode.OUT_OF_RANGE
    assert exception.message == message
    assert exception.errors == []


def test_from_grpc_status_with_errors_and_response():
    message = "message"
    response = mock.sentinel.response
    errors = ["1", "2"]
    exception = exceptions.from_grpc_status(
        grpc.StatusCode.OUT_OF_RANGE, message, errors=errors, response=response
    )

    assert isinstance(exception, exceptions.OutOfRange)
    assert exception.message == message
    assert exception.errors == errors
    assert exception.response == response


def test_from_grpc_status_unknown_code():
    message = "message"
    exception = exceptions.from_grpc_status(grpc.StatusCode.OK, message)
    assert exception.grpc_status_code == grpc.StatusCode.OK
    assert exception.message == message


def test_from_grpc_error():
    message = "message"
    error = mock.create_autospec(grpc.Call, instance=True)
    error.code.return_value = grpc.StatusCode.INVALID_ARGUMENT
    error.details.return_value = message

    exception = exceptions.from_grpc_error(error)

    assert isinstance(exception, exceptions.BadRequest)
    assert isinstance(exception, exceptions.InvalidArgument)
    assert exception.code == http.client.BAD_REQUEST
    assert exception.grpc_status_code == grpc.StatusCode.INVALID_ARGUMENT
    assert exception.message == message
    assert exception.errors == [error]
    assert exception.response == error


def test_from_grpc_error_non_call():
    message = "message"
    error = mock.create_autospec(grpc.RpcError, instance=True)
    error.__str__.return_value = message

    exception = exceptions.from_grpc_error(error)

    assert isinstance(exception, exceptions.GoogleAPICallError)
    assert exception.code is None
    assert exception.grpc_status_code is None
    assert exception.message == message
    assert exception.errors == [error]
    assert exception.response == error


def create_bad_request_details():
    bad_request_details = error_details_pb2.BadRequest()
    field_violation = bad_request_details.field_violations.add()
    field_violation.field = "document.content"
    field_violation.description = "Must have some text content to annotate."
    status_detail = any_pb2.Any()
    status_detail.Pack(bad_request_details)
    return status_detail
    

def test_error_details_from_rest_response():
    bad_request_detail = create_bad_request_details()
    status = rpc_status.status_pb2.Status()
    status.code = 3
    status.message = (
        "3 INVALID_ARGUMENT: One of content, or gcs_content_uri must be set."
    )
    status.details.append(bad_request_detail)

    # See JSON schema in https://cloud.google.com/apis/design/errors#http_mapping
    http_response = make_response(
        json.dumps({"error": json.loads(json_format.MessageToJson(status))}).encode(
            "utf-8"
        )
    )
    exception = exceptions.from_http_response(http_response)
    want_error_details = [json.loads(json_format.MessageToJson(bad_request_detail))]
    assert want_error_details == exception.error_details


def test_error_details_from_v1_rest_response():
    response = make_response(
        json.dumps(
            {"error": {"message": "\u2019 message", "errors": ["1", "2"]}}
        ).encode("utf-8")
    )
    exception = exceptions.from_http_response(response)
    assert exception.error_details == []


def test_error_details_from_grpc_response():
    status = rpc_status.status_pb2.Status()
    status.code = 3
    status.message = (
        "3 INVALID_ARGUMENT: One of content, or gcs_content_uri must be set."
    )
    status_detail = create_bad_request_details()
    status.details.append(status_detail)

    # Actualy error doesn't matter as long as its grpc.Call,
    # because from_call is mocked.
    error = mock.create_autospec(grpc.Call, instance=True)
    with mock.patch('grpc_status.rpc_status.from_call') as m:
        m.return_value = status
        exception = exceptions.from_grpc_error(error)
    
    bad_request_detail = error_details_pb2.BadRequest()
    status_detail.Unpack(bad_request_detail)
    assert exception.error_details == [bad_request_detail]