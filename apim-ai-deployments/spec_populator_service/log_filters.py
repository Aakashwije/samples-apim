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


class EndpointFilter(logging.Filter):
    """Filter class to exclude specific endpoints from log entries."""

    def __init__(self, excluded_endpoints: list[str]) -> None:
        """
        Initialize the EndpointFilter class.

        Args:
            excluded_endpoints: A list of endpoints to be excluded from log entries.
        """
        self.excluded_endpoints = excluded_endpoints

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter out log entries for excluded endpoints.

        Args:
            record: The log record to be filtered.

        Returns:
            bool: True if the log entry should be included, False otherwise.
        """
        # return record.args and len(record.args) >= 3 and record.args[2] not in self.excluded_endpoints

        if not record.args or len(record.args) < 3:
            return True  # If there are no arguments or not enough arguments, include the log.

        url_path = record.args[2]

        # Check if the URL has query parameters
        has_query_params = '?' in url_path

        # Extract the base path before any query parameters
        base_path = url_path.split('?', 1)[0]

        # If the base path is in the excluded endpoints or the URL has query parameters, exclude it
        if base_path in self.excluded_endpoints or has_query_params:
            return False

        return True
