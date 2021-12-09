# Copyright 2021 Google LLC
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

"""Helpers for server-side streaming in REST."""

import json
import string

import requests


class ResponseIterator:
    """Iterator over REST API responses.

    Args:
        response (requests.Response): An API response object.
        response_message_cls (Callable[proto.Message]): A proto
        class expected to be returned from an API.
    """

    def __init__(self, response: requests.Response, response_message_cls):
        self._response = response
        self._response_message_cls = response_message_cls
        # Inner iterator over HTTP response's content.
        self._response_itr = self._response.iter_content(decode_unicode=True)
        # Contains a list of JSON responses ready to be sent to user.
        self._ready_objs = []
        # Current JSON response being built.
        self._obj = ""
        # Keeps track of the nesting level within a JSON object.
        self._level = 0
        # Keeps track whether HTTP response is currently sending values
        # inside of a string value.
        self._in_string = False

    def cancel(self):
        """Cancel existing streaming operation.
        """
        self._response.close()

    def _process_chunk(self, chunk: str):
        if self._level == 0:
            if chunk[0] != "[":
                raise ValueError(
                    "Can only parse array of JSON objects, instead got %s" % chunk
                )
        for char in chunk:
            if char == "{":
                if self._level == 1:
                    # Level 1 corresponds to the outermost JSON object
                    # (i.e. the one we care about).
                    self._obj = ""
                if not self._in_string:
                    self._level += 1
                self._obj += char
            elif char == '"':
                self._in_string = not self._in_string
                self._obj += char
            elif char == "}":
                self._obj += char
                if not self._in_string:
                    self._level -= 1
                if not self._in_string and self._level == 1:
                    self._ready_objs.append(self._obj)
            elif char in string.whitespace:
                if self._in_string:
                    self._obj += char
            elif char == "[":
                self._level += 1
            elif char == "]":
                self._level -= 1
            else:
                self._obj += char

    def __next__(self):
        while not self._ready_objs:
            chunk = next(self._response_itr)
            self._process_chunk(chunk)
        return self._grab()

    def _grab(self):
        obj = self._ready_objs[0]
        self._ready_objs = self._ready_objs[1:]
        # Add extra quotes to make json.loads happy.
        return self._response_message_cls.from_json(json.loads('"' + obj + '"'))

    def __iter__(self):
        return self
