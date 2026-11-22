# the image of the bash sandbox and of the reader containers of the contacts' files (SandboxVolume.SANDBOX_IMAGE): llm
# sandbox's python image (python 3.11, git, curl, gcc, g++, make, pkg-config on debian bullseye) with cmake and ninja for
# C and C++ builds. the sandbox runs as a user, it can't apt-get: what a job's project needs has to be here.
# from pypi, not apt: bullseye's cmake is 3.18, too old for many projects (cmake_minimum_required 3.20 and newer),
# bullseye-backports is archived and bullseye-security answers 404 for many packages since its end of life (apt-get
# install fails). cmake stays below 4, which refuses projects written for cmake older than 3.5
FROM ghcr.io/vndee/sandbox-python-311-bullseye

RUN pip install --no-cache-dir "cmake>=3.31,<4" "ninja>=1.11,<2" \
    && cmake --version && ninja --version
