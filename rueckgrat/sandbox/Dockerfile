# the image of the contacts' sandbox containers and of the reader containers of their files (SandboxVolume.SANDBOX_IMAGE,
# SandboxContainer): python 3.11 on debian trixie, the full image (buildpack-deps: git, curl, wget, gcc, g++, make,
# autoconf, libtool and the common -dev libraries), SDL2 for games, cmake and ninja for C and C++ builds and the python
# libraries in the system python3. the sandbox runs as the user sandbox (uid 1000, SANDBOX_USER, its home the contact's
# files at /home) with passwordless sudo: sudo apt-get install works in the contact's container while it lives, and
# what it installs is installed again in a container of a newer image
FROM python:3.11-trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
        sudo pkg-config \
        libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-mixer-dev libgl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --home-dir /home --no-create-home --shell /bin/bash sandbox \
    && echo "sandbox ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/sandbox && chmod 0440 /etc/sudoers.d/sandbox

# cmake from pypi: stays below 4, which refuses projects written for cmake older than 3.5
RUN pip install --no-cache-dir "cmake>=3.31,<4" "ninja>=1.11,<2" \
        numpy pandas matplotlib pillow seaborn scikit-learn scipy scikit-image plotly \
    && cmake --version && ninja --version

# the packages installed beyond the image's, written after every apt run (dpkg's Post-Invoke) with the contact's files
# (SandboxVolume APT_PACKAGES): the hub installs them again in a container made for a newer image (SandboxContainer)
RUN apt-mark showmanual | sort > /etc/rueckgrat-packages \
    && printf '%s\n' '#!/bin/sh' \
        'mkdir -p /home/.cache/rueckgrat' \
        'apt-mark showmanual | sort | comm -13 /etc/rueckgrat-packages - > /home/.cache/rueckgrat/apt-packages' \
        'chown 1000:1000 /home/.cache /home/.cache/rueckgrat /home/.cache/rueckgrat/apt-packages' \
        > /usr/local/sbin/rueckgrat-packages \
    && chmod 755 /usr/local/sbin/rueckgrat-packages \
    && echo 'DPkg::Post-Invoke { "/usr/local/sbin/rueckgrat-packages || true"; };' > /etc/apt/apt.conf.d/99rueckgrat-packages
