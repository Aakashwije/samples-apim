# Copyright (c) 2026, WSO2 LLC. (https://www.wso2.com).
#
# WSO2 LLC. licenses this file to you under the Apache License,
# Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.
FROM choreocontrolplane.azurecr.io/ubuntu:20.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3.9=3.9.5-3ubuntu0~20.04.1 \
      python3-pip \
      python3.9-venv=3.9.5-3ubuntu0~20.04.1 && \
    apt-get install -y g++ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    python3.9 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /tmp
COPY requirements.txt .
RUN pip3 install --upgrade pip && \
    pip3 --no-cache-dir install --upgrade wheel && \
    pip3 --no-cache-dir install --upgrade setuptools && \
    pip3 --no-cache-dir install -r requirements.txt  
    # building wheel for modules fail if wheel is not
    # already installed. Hence the reason to execute a separate pip3
    # install for wheel before installing requirements


FROM choreocontrolplane.azurecr.io/ubuntu:20.04

ARG GROUP=ai
ARG USER=python-ai
ARG USER_ID=10500
ARG USER_GROUP_ID=10500

RUN groupadd --system --gid ${USER_GROUP_ID} ${GROUP} && \
    useradd --system --create-home --home-dir /home/${USER} --no-log-init --gid ${USER_GROUP_ID} --uid ${USER_ID} ${USER} && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      python3.9=3.9.5-3ubuntu0~20.04.1 \
      python3-pip \
      python3.9-venv=3.9.5-3ubuntu0~20.04.1 \
      libncurses6=6.2-0ubuntu2.1 \
      libncursesw6=6.2-0ubuntu2.1 \
      libtinfo6=6.2-0ubuntu2.1 \
      ncurses-base=6.2-0ubuntu2.1 \
      ncurses-bin=6.2-0ubuntu2.1 \
      perl-base=5.30.0-9ubuntu0.5 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/${USER}/spec_populator_service

COPY --from=builder --chown=${USER}:${GROUP} /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# sources
COPY --chown=${USER}:${GROUP} / spec_populator_service/

WORKDIR /home/${USER}/spec_populator_service/spec_populator_service

USER ${USER}

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
